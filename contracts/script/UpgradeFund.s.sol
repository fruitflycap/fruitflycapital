// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";
import {ITransparentUpgradeableProxy} from "@openzeppelin/contracts/proxy/transparent/TransparentUpgradeableProxy.sol";
import {ProxyAdmin} from "@openzeppelin/contracts/proxy/transparent/ProxyAdmin.sol";
import {FruitFlyFundVault} from "../src/FruitFlyFundVault.sol";

/// @notice Deploy a new vault implementation and upgrade the configured proxy.
/// @dev The deployer key must own the proxy's ProxyAdmin. No initializer call
/// is needed for a storage-compatible implementation-only upgrade.
contract UpgradeFund is Script {
    bytes32 private constant ADMIN_SLOT =
        0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103;

    function run() external returns (address implementation) {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address proxyAddress = vm.envAddress("FUND_CONTRACT_ADDRESS");
        address proxyAdminAddress = address(uint160(uint256(vm.load(proxyAddress, ADMIN_SLOT))));
        require(proxyAdminAddress != address(0), "proxy admin not found");

        vm.startBroadcast(deployerKey);
        FruitFlyFundVault nextImplementation = new FruitFlyFundVault();
        ProxyAdmin(proxyAdminAddress).upgradeAndCall(
            ITransparentUpgradeableProxy(proxyAddress),
            address(nextImplementation),
            bytes("")
        );
        vm.stopBroadcast();

        implementation = address(nextImplementation);
        console2.log("FruitFlyFundVault proxy", proxyAddress);
        console2.log("ProxyAdmin", proxyAdminAddress);
        console2.log("New implementation", implementation);
    }
}
