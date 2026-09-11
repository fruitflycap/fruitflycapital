// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Initializable} from "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

interface IWETH {
    function deposit() external payable;
}

/// @notice Explicit-share accounting for a multichain strategy fund.
/// @dev This is the implementation behind an OpenZeppelin transparent proxy.
/// V1 uses an authorized offchain NAV reporter; it is not trustless production
/// fund accounting. Upgrades are performed by the separate ProxyAdmin created
/// by TransparentUpgradeableProxy, never by a fund operating role.
contract FruitFlyFundVault is Initializable, ERC20, AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant STRATEGY_ROLE = keccak256("STRATEGY_ROLE");
    bytes32 public constant NAV_REPORTER_ROLE = keccak256("NAV_REPORTER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");
    uint256 private constant SHARE_SCALE = 1e18;

    IERC20 public accountingAsset;
    uint256 public assetScale;
    address public strategyTreasury;
    uint256 public reportedStrategyNavAsset;
    uint256 public lastNavReportTimestamp;

    enum WithdrawalStatus { NONE, REQUESTED, FUNDED, CLAIMED }
    struct WithdrawalRequest {
        address owner;
        uint256 shares;
        uint256 amountAsset;
        uint256 navPerShareAsset;
        WithdrawalStatus status;
    }

    uint256 public nextWithdrawalId = 1;
    mapping(uint256 => WithdrawalRequest) public withdrawalRequests;

    event Deposit(address indexed caller, address indexed owner, uint256 assets, uint256 shares);
    event NativeDeposit(address indexed caller, address indexed owner, uint256 assets, uint256 shares);
    event CapitalDeployed(address indexed treasury, uint256 amount);
    event StrategyNavReported(uint256 strategyNavAsset, uint256 totalNavAsset, uint256 navPerShareAsset, uint256 timestamp);
    event WithdrawalRequested(uint256 indexed requestId, address indexed owner, uint256 shares, uint256 amountAsset, uint256 navPerShareAsset);
    event WithdrawalFunded(uint256 indexed requestId, uint256 amountAsset);
    event WithdrawalClaimed(uint256 indexed requestId, address indexed owner, uint256 amountAsset);
    event StrategyTreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);

    constructor()
        ERC20("Fruit Fly Capital Fund Share", "FFC")
    {
        // The implementation contract must never be initialized directly.
        // Initialization happens atomically through the proxy constructor.
        _disableInitializers();
    }

    function initialize(address asset, address treasury, address admin) external initializer {
        require(asset != address(0) && treasury != address(0) && admin != address(0), "zero address");
        uint8 decimals = IERC20Metadata(asset).decimals();
        require(decimals <= 18, "asset decimals too high");
        accountingAsset = IERC20(asset);
        assetScale = 10 ** decimals;
        strategyTreasury = treasury;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(STRATEGY_ROLE, admin);
        _grantRole(NAV_REPORTER_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
    }

    // ERC20 stores name and symbol in constructor-only storage. The proxy's
    // implementation constructor cannot initialize proxy storage, so expose
    // the immutable product metadata explicitly from the logic contract.
    function name() public pure override returns (string memory) {
        return "Fruit Fly Capital Fund Share";
    }

    function symbol() public pure override returns (string memory) {
        return "FFC";
    }

    function totalNavAsset() public view returns (uint256) {
        return accountingAsset.balanceOf(address(this)) + reportedStrategyNavAsset;
    }

    /// @return Accounting-asset base units represented by one whole share unit.
    function navPerShareAsset() public view returns (uint256) {
        if (totalSupply() == 0) return assetScale;
        return Math.mulDiv(totalNavAsset(), SHARE_SCALE, totalSupply());
    }

    function deposit(uint256 assets, address receiver) external nonReentrant whenNotPaused returns (uint256 shares) {
        require(assets > 0 && receiver != address(0), "invalid deposit");
        shares = _sharesForDeposit(assets, navPerShareAsset());
        accountingAsset.safeTransferFrom(msg.sender, address(this), assets);
        _completeDeposit(msg.sender, receiver, assets, shares);
    }

    /// @notice Wrap native ETH into the configured WETH asset and mint FFC shares.
    /// @dev The deployed Robinhood testnet vault is configured with WETH.
    function depositETH(address receiver) external payable nonReentrant whenNotPaused returns (uint256 shares) {
        require(msg.value > 0 && receiver != address(0), "invalid deposit");
        shares = _sharesForDeposit(msg.value, navPerShareAsset());
        IWETH(address(accountingAsset)).deposit{value: msg.value}();
        _completeDeposit(msg.sender, receiver, msg.value, shares);
        emit NativeDeposit(msg.sender, receiver, msg.value, shares);
    }

    /// @notice A plain ETH transfer deposits for the sending address.
    /// @dev This makes sending ETH to the fund proxy equivalent to
    /// depositETH(msg.sender). Sending ETH to WETH itself only wraps it.
    receive() external payable nonReentrant whenNotPaused {
        require(msg.value > 0, "invalid deposit");
        uint256 shares = _sharesForDeposit(msg.value, navPerShareAsset());
        IWETH(address(accountingAsset)).deposit{value: msg.value}();
        _completeDeposit(msg.sender, msg.sender, msg.value, shares);
        emit NativeDeposit(msg.sender, msg.sender, msg.value, shares);
    }

    function _sharesForDeposit(uint256 assets, uint256 price) private pure returns (uint256 shares) {
        shares = Math.mulDiv(assets, SHARE_SCALE, price);
        require(shares > 0, "rounding to zero");
    }

    function _completeDeposit(address caller, address receiver, uint256 assets, uint256 shares) private {
        _mint(receiver, shares);
        emit Deposit(caller, receiver, assets, shares);
    }

    function deployCapital(uint256 amount) external onlyRole(STRATEGY_ROLE) whenNotPaused {
        require(amount > 0 && amount <= accountingAsset.balanceOf(address(this)), "invalid deployment");
        accountingAsset.safeTransfer(strategyTreasury, amount);
        emit CapitalDeployed(strategyTreasury, amount);
    }

    function setStrategyTreasury(address newTreasury) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(newTreasury != address(0), "zero treasury");
        address oldTreasury = strategyTreasury;
        strategyTreasury = newTreasury;
        emit StrategyTreasuryUpdated(oldTreasury, newTreasury);
    }

    function reportStrategyNav(uint256 strategyNavAsset) external onlyRole(NAV_REPORTER_ROLE) whenNotPaused {
        reportedStrategyNavAsset = strategyNavAsset;
        lastNavReportTimestamp = block.timestamp;
        emit StrategyNavReported(strategyNavAsset, totalNavAsset(), navPerShareAsset(), block.timestamp);
    }

    function requestRedeem(uint256 shares) external nonReentrant whenNotPaused returns (uint256 requestId) {
        require(shares > 0 && shares <= balanceOf(msg.sender), "invalid redemption");
        uint256 price = navPerShareAsset();
        uint256 amountAsset = Math.mulDiv(shares, price, SHARE_SCALE);
        require(amountAsset > 0, "rounding to zero");
        // Escrow shares until claim; this keeps the request's NAV snapshot
        // explicit and prevents the owner from spending them twice.
        _transfer(msg.sender, address(this), shares);
        requestId = nextWithdrawalId++;
        withdrawalRequests[requestId] = WithdrawalRequest(msg.sender, shares, amountAsset, price, WithdrawalStatus.REQUESTED);
        emit WithdrawalRequested(requestId, msg.sender, shares, amountAsset, price);
    }

    function fundWithdrawal(uint256 requestId) external onlyRole(STRATEGY_ROLE) whenNotPaused {
        WithdrawalRequest storage request = withdrawalRequests[requestId];
        require(request.status == WithdrawalStatus.REQUESTED, "not requested");
        require(request.amountAsset <= accountingAsset.balanceOf(address(this)), "insufficient liquidity");
        request.status = WithdrawalStatus.FUNDED;
        emit WithdrawalFunded(requestId, request.amountAsset);
    }

    function claimWithdrawal(uint256 requestId) external nonReentrant whenNotPaused {
        WithdrawalRequest storage request = withdrawalRequests[requestId];
        require(request.owner == msg.sender && request.status == WithdrawalStatus.FUNDED, "not claimable");
        request.status = WithdrawalStatus.CLAIMED;
        _burn(address(this), request.shares);
        accountingAsset.safeTransfer(msg.sender, request.amountAsset);
        emit WithdrawalClaimed(requestId, msg.sender, request.amountAsset);
    }

    // Read-only aliases retained for the prototype dashboard and older tests.
    // New integrations should use the generic asset-named functions above.
    function totalNavUsdc() public view returns (uint256) { return totalNavAsset(); }
    function navPerShareUsdc() public view returns (uint256) { return navPerShareAsset(); }
    function reportedStrategyNavUsdc() public view returns (uint256) { return reportedStrategyNavAsset; }

    function pause() external onlyRole(PAUSER_ROLE) { _pause(); }
    function unpause() external onlyRole(PAUSER_ROLE) { _unpause(); }

    // Reserve room for future state variables. New implementations must only
    // append fields before this gap and preserve the existing order/types.
    uint256[50] private __gap;
}
