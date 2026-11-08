// Metro must see the shared packages outside the app directory (monorepo).
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);
config.watchFolders = [
  path.resolve(__dirname, "../../packages/sync-core"),
  path.resolve(__dirname, "../../packages/shared"),
];
config.resolver.nodeModulesPaths = [path.resolve(__dirname, "node_modules")];

module.exports = config;
