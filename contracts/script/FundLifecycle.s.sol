// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";
import {FruitFlyFundVault} from "../src/FruitFlyFundVault.sol";

interface IWETH {
    function deposit() external payable;
    function approve(address spender, uint256 amount) external returns (bool);
    function balanceOf(address owner) external view returns (uint256);
}

contract FundLifecycle is Script {
    function run() external {
        uint256 key = vm.envUint("PRIVATE_KEY");
        IWETH weth = IWETH(vm.envAddress("FUND_WETH_ADDRESS"));
        FruitFlyFundVault vault = FruitFlyFundVault(vm.envAddress("FUND_CONTRACT_ADDRESS"));
        address alice = vm.addr(key);
        uint256 amount = vm.envOr("FUND_TEST_DEPOSIT_WEI", uint256(0.0001 ether));
        require(address(vault.accountingAsset()) == address(weth), "vault asset is not configured WETH");
        vm.startBroadcast(key);
        weth.deposit{value: amount}();
        weth.approve(address(vault), amount);
        vault.deposit(amount, alice);
        vault.deployCapital(amount / 2);
        vault.reportStrategyNav(amount / 2);
        console2.log("Alice shares", vault.balanceOf(alice));
        console2.log("NAV/share (WETH base units)", vault.navPerShareAsset());
        vm.stopBroadcast();
    }
}
