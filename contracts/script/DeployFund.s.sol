// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";
import {TransparentUpgradeableProxy} from "@openzeppelin/contracts/proxy/transparent/TransparentUpgradeableProxy.sol";
import {FruitFlyFundVault} from "../src/FruitFlyFundVault.sol";

contract DeployFund is Script {
    function run() external returns (FruitFlyFundVault vault) {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address admin = vm.addr(deployerKey);
        address weth = vm.envAddress("FUND_WETH_ADDRESS");
        address treasury = vm.envOr("PRIVY_WALLET_ADDRESS", admin);
        vm.startBroadcast(deployerKey);
        FruitFlyFundVault implementation = new FruitFlyFundVault();
        bytes memory initialization = abi.encodeCall(
            FruitFlyFundVault.initialize,
            (weth, treasury, admin)
        );
        TransparentUpgradeableProxy proxy = new TransparentUpgradeableProxy(
            address(implementation),
            admin,
            initialization
        );
        vault = FruitFlyFundVault(address(proxy));
        vm.stopBroadcast();
        console2.log("Robinhood Chain testnet WETH", weth);
        console2.log("FruitFlyFundVault proxy", address(vault));
        console2.log("FruitFlyFundVault implementation", address(implementation));
        console2.log("ProxyAdmin", _proxyAdmin(address(proxy)));
        console2.log("Strategy treasury", treasury);
    }

    function _proxyAdmin(address proxy) private view returns (address) {
        bytes32 adminSlot = 0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103;
        return address(uint160(uint256(vm.load(proxy, adminSlot))));
    }
}
