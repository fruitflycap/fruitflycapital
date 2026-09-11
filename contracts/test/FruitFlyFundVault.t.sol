// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {ITransparentUpgradeableProxy, TransparentUpgradeableProxy} from "@openzeppelin/contracts/proxy/transparent/TransparentUpgradeableProxy.sol";
import {ProxyAdmin} from "@openzeppelin/contracts/proxy/transparent/ProxyAdmin.sol";
import {FruitFlyFundVault} from "../src/FruitFlyFundVault.sol";
import {MockUSDC} from "../src/mocks/MockUSDC.sol";
import {MockWETH} from "../src/mocks/MockWETH.sol";

contract FruitFlyFundVaultTest is Test {
    MockUSDC usdc;
    FruitFlyFundVault vault;
    address admin = makeAddr("admin");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address charlie = makeAddr("charlie");
    address treasury = makeAddr("treasury");

    function setUp() public {
        usdc = new MockUSDC();
        FruitFlyFundVault implementation = new FruitFlyFundVault();
        bytes memory initialization = abi.encodeCall(
            FruitFlyFundVault.initialize,
            (address(usdc), treasury, admin)
        );
        TransparentUpgradeableProxy proxy = new TransparentUpgradeableProxy(
            address(implementation),
            admin,
            initialization
        );
        vault = FruitFlyFundVault(payable(address(proxy)));
        usdc.mint(alice, 1_000e6);
        usdc.mint(bob, 1_000e6);
        usdc.mint(charlie, 1_000e6);
        vm.prank(alice); usdc.approve(address(vault), type(uint256).max);
        vm.prank(bob); usdc.approve(address(vault), type(uint256).max);
        vm.prank(charlie); usdc.approve(address(vault), type(uint256).max);
    }

    function testFirstDepositMintsOneToOneShares() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        assertEq(vault.balanceOf(alice), 100e18);
        assertEq(vault.navPerShareUsdc(), 1e6);
        assertEq(vault.name(), "Fruit Fly Capital Fund Share");
        assertEq(vault.symbol(), "FFC");
        console2.log("first deposit shares", vault.balanceOf(alice));
    }

    function testProxyAndImplementationCannotBeInitializedTwice() public {
        vm.expectRevert();
        vault.initialize(address(usdc), treasury, admin);

        FruitFlyFundVault implementation = new FruitFlyFundVault();
        vm.expectRevert();
        implementation.initialize(address(usdc), treasury, admin);
    }

    function testSecondDepositorAtInitialNav() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(bob); vault.deposit(100e6, bob);
        assertEq(vault.balanceOf(bob), 100e18);
        assertEq(vault.totalSupply(), 200e18);
    }

    function testDeploymentLeavesLiquidCashAndKeepsNav() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(admin); vault.deployCapital(40e6);
        assertEq(usdc.balanceOf(address(vault)), 60e6);
        assertEq(usdc.balanceOf(treasury), 40e6);
        assertEq(vault.totalNavUsdc(), 60e6);
        vm.prank(admin); vault.reportStrategyNav(40e6);
        assertEq(vault.totalNavUsdc(), 100e6);
    }

    function testStrategyGainRaisesNavAndLaterDepositGetsFewerShares() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(admin); vault.deployCapital(50e6);
        vm.prank(admin); vault.reportStrategyNav(60e6);
        assertEq(vault.navPerShareUsdc(), 1_100_000);
        vm.prank(bob); vault.deposit(110e6, bob);
        assertEq(vault.balanceOf(bob), 100e18);
        assertEq(vault.navPerShareUsdc(), 1_100_000);
    }

    function testStrategyLossLowersNav() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(admin); vault.deployCapital(50e6);
        vm.prank(admin); vault.reportStrategyNav(40e6);
        assertEq(vault.navPerShareUsdc(), 900_000);
    }

    function testWithdrawalLifecycleUsesRequestSnapshot() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(admin); vault.deployCapital(50e6);
        vm.prank(admin); vault.reportStrategyNav(60e6);
        vm.prank(alice); uint256 requestId = vault.requestRedeem(50e18);
        (address owner, uint256 shares, uint256 amount, uint256 price, FruitFlyFundVault.WithdrawalStatus status) = vault.withdrawalRequests(requestId);
        assertEq(owner, alice); assertEq(shares, 50e18); assertEq(amount, 55e6); assertEq(price, 1_100_000);
        assertEq(uint256(status), uint256(FruitFlyFundVault.WithdrawalStatus.REQUESTED));
        vm.prank(alice); vm.expectRevert("not claimable"); vault.claimWithdrawal(requestId);
        vm.prank(treasury); usdc.transfer(address(vault), 10e6);
        vm.prank(admin); vault.fundWithdrawal(requestId);
        vm.prank(alice); vault.claimWithdrawal(requestId);
        assertEq(usdc.balanceOf(alice), 955e6);
        vm.prank(alice); vm.expectRevert("not claimable"); vault.claimWithdrawal(requestId);
    }

    function testReturnCapitalFundsWithdrawal() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(admin); vault.deployCapital(80e6);
        vm.prank(admin); vault.reportStrategyNav(80e6);
        vm.prank(alice); uint256 requestId = vault.requestRedeem(60e18);
        vm.prank(admin); vm.expectRevert("insufficient liquidity"); vault.fundWithdrawal(requestId);
        vm.prank(treasury); usdc.transfer(address(vault), 60e6);
        vm.prank(admin); vault.fundWithdrawal(requestId);
        vm.prank(alice); vault.claimWithdrawal(requestId);
        assertEq(usdc.balanceOf(alice), 960e6);
    }

    function testUnauthorizedOperationsRevert() public {
        vm.prank(alice); vm.expectRevert(); vault.deployCapital(1e6);
        vm.prank(alice); vm.expectRevert(); vault.reportStrategyNav(1e6);
        vm.prank(alice); vm.expectRevert(); vault.setStrategyTreasury(alice);
    }

    function testPausePreventsDepositsDeploymentAndReports() public {
        vm.prank(admin); vault.pause();
        vm.prank(alice); vm.expectRevert(); vault.deposit(1e6, alice);
        vm.prank(admin); vm.expectRevert(); vault.deployCapital(1e6);
        vm.prank(admin); vm.expectRevert(); vault.reportStrategyNav(1e6);
        vm.prank(admin); vault.unpause();
        vm.prank(alice); vault.deposit(1e6, alice);
    }

    function testZeroAndRoundingInputsRejected() public {
        vm.prank(alice); vm.expectRevert("invalid deposit"); vault.deposit(0, alice);
        vm.prank(alice); vm.expectRevert("invalid redemption"); vault.requestRedeem(0);
    }

    function testPlainEthTransferToWethVaultWrapsAndMintsShares() public {
        MockWETH weth = new MockWETH();
        FruitFlyFundVault wethVault = _deployVault(address(weth));
        vm.deal(alice, 1 ether);

        vm.prank(alice);
        (bool success,) = address(wethVault).call{value: 0.1 ether}("");

        assertTrue(success);
        assertEq(weth.balanceOf(address(wethVault)), 0.1 ether);
        assertEq(wethVault.balanceOf(alice), 0.1 ether);
        assertEq(wethVault.totalNavAsset(), 0.1 ether);
    }

    function testExplicitEthDepositCanMintToReceiver() public {
        MockWETH weth = new MockWETH();
        FruitFlyFundVault wethVault = _deployVault(address(weth));
        vm.deal(alice, 1 ether);

        vm.prank(alice);
        wethVault.depositETH{value: 0.1 ether}(bob);

        assertEq(weth.balanceOf(address(wethVault)), 0.1 ether);
        assertEq(wethVault.balanceOf(bob), 0.1 ether);
        assertEq(alice.balance, 0.9 ether);
    }

    function testSendingEthToWethDoesNotMintFundShares() public {
        MockWETH weth = new MockWETH();
        FruitFlyFundVault wethVault = _deployVault(address(weth));
        vm.deal(alice, 1 ether);

        vm.prank(alice);
        (bool success,) = address(weth).call{value: 0.1 ether}("");

        assertTrue(success);
        assertEq(weth.balanceOf(alice), 0.1 ether);
        assertEq(wethVault.balanceOf(alice), 0);
        assertEq(wethVault.totalNavAsset(), 0);
    }

    function _deployVault(address asset) private returns (FruitFlyFundVault deployed) {
        FruitFlyFundVault implementation = new FruitFlyFundVault();
        bytes memory initialization = abi.encodeCall(
            FruitFlyFundVault.initialize,
            (asset, treasury, admin)
        );
        TransparentUpgradeableProxy proxy = new TransparentUpgradeableProxy(
            address(implementation),
            admin,
            initialization
        );
        deployed = FruitFlyFundVault(payable(address(proxy)));
    }

    function testMultipleInvestorsAndRoundingDoNotCreateFreeShares() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(admin); vault.reportStrategyNav(100e6);
        vm.prank(bob); vault.deposit(1, bob);
        assertGt(vault.balanceOf(bob), 0);
        assertLe(vault.totalSupply(), 100e18 + 1e12);
        assertEq(vault.totalNavUsdc(), usdc.balanceOf(address(vault)) + vault.reportedStrategyNavUsdc());
        vm.prank(charlie); vm.expectRevert("invalid deposit"); vault.deposit(0, charlie);
    }

    function testProxyUpgradePreservesStateAndRoles() public {
        vm.prank(alice); vault.deposit(100e6, alice);
        vm.prank(admin); vault.reportStrategyNav(25e6);

        FruitFlyFundVaultV2 nextImplementation = new FruitFlyFundVaultV2();
        address proxyAdminAddress = address(uint160(uint256(vm.load(address(vault), _adminSlot()))));
        vm.prank(admin);
        ProxyAdmin(proxyAdminAddress).upgradeAndCall(
            ITransparentUpgradeableProxy(address(vault)),
            address(nextImplementation),
            bytes("")
        );

        FruitFlyFundVaultV2 upgraded = FruitFlyFundVaultV2(payable(address(vault)));
        assertEq(upgraded.version(), 2);
        assertEq(upgraded.balanceOf(alice), 100e18);
        assertEq(upgraded.totalNavUsdc(), 125e6);
        assertEq(address(upgraded.accountingAsset()), address(usdc));
        assertEq(upgraded.strategyTreasury(), treasury);
        assertTrue(upgraded.hasRole(upgraded.DEFAULT_ADMIN_ROLE(), admin));
    }

    function _adminSlot() private pure returns (bytes32) {
        return 0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103;
    }
}

contract FruitFlyFundVaultV2 is FruitFlyFundVault {
    function version() external pure returns (uint256) {
        return 2;
    }
}
