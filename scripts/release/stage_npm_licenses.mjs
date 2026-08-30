import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const [nodeModulesRoot, outputRoot, overrideRoot] = process.argv.slice(2);
if (!nodeModulesRoot || !outputRoot || !overrideRoot) {
  throw new Error("usage: stage_npm_licenses.mjs NODE_MODULES OUTPUT_DIR OVERRIDE_DIR");
}

const legalName = /^(?:licen[cs]e|copying|copyright|notice)(?:[._-].*)?$/i;
const packages = [];

function packageDirectories(modulesDirectory) {
  if (!fs.existsSync(modulesDirectory)) return [];
  const directories = [];
  for (const entry of fs.readdirSync(modulesDirectory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isDirectory() || entry.name === ".bin") continue;
    const entryPath = path.join(modulesDirectory, entry.name);
    if (entry.name.startsWith("@")) {
      for (const scoped of fs.readdirSync(entryPath, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
        if (scoped.isDirectory()) directories.push(path.join(entryPath, scoped.name));
      }
    } else {
      directories.push(entryPath);
    }
  }
  return directories;
}

function legalFiles(packageRoot) {
  return fs.readdirSync(packageRoot, { withFileTypes: true })
    .filter((entry) => entry.isFile() && legalName.test(entry.name))
    .map((entry) => path.join(packageRoot, entry.name))
    .sort();
}

function visit(modulesDirectory) {
  for (const packageRoot of packageDirectories(modulesDirectory)) {
    const metadataPath = path.join(packageRoot, "package.json");
    if (!fs.existsSync(metadataPath)) throw new Error(`npm package metadata is missing: ${packageRoot}`);
    const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
    if (!metadata.name || !metadata.version) throw new Error(`npm package identity is missing: ${packageRoot}`);
    let sources = legalFiles(packageRoot);
    if (sources.length === 0) {
      const overrideName = `${metadata.name.replace(/[^A-Za-z0-9._-]/g, "-")}-${metadata.version}`;
      const reviewedOverride = path.join(overrideRoot, overrideName);
      if (fs.existsSync(reviewedOverride)) sources = legalFiles(reviewedOverride);
    }
    if (sources.length === 0) throw new Error(`npm package has no license text: ${metadata.name}@${metadata.version}`);
    const relativePackagePath = path.relative(nodeModulesRoot, packageRoot).split(path.sep).join("/");
    const pathDigest = crypto.createHash("sha256").update(relativePackagePath).digest("hex").slice(0, 10);
    const safeName = metadata.name.replace(/[^A-Za-z0-9._-]/g, "-").replace(/^-+|-+$/g, "");
    const componentRoot = path.join(outputRoot, `${safeName}-${metadata.version}-${pathDigest}`);
    const copied = [];
    for (const source of sources) {
      const target = path.join(componentRoot, path.basename(source));
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(source, target);
      copied.push(path.relative(outputRoot, target).split(path.sep).join("/"));
    }
    packages.push({ name: metadata.name, version: metadata.version, packagePath: relativePackagePath, files: copied });
    visit(path.join(packageRoot, "node_modules"));
  }
}

fs.mkdirSync(path.dirname(outputRoot), { recursive: true });
fs.mkdirSync(outputRoot);
visit(nodeModulesRoot);
packages.sort((left, right) => left.packagePath.localeCompare(right.packagePath));
fs.writeFileSync(path.join(outputRoot, "LICENSES.json"), `${JSON.stringify(packages, null, 2)}\n`);
