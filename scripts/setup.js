#!/usr/bin/env node

/**
 * Setup script for EA Bot project
 * Run from project root: node scripts/setup.js
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const rootDir = process.cwd();
const nodePath = '/c/Users/billy/AppData/Local/hermes/node/node';
const npmPath = '/c/Users/billy/AppData/Local/hermes/node/npm';

console.log('=== EA Bot Project Setup ===\n');

// Check Node.js
console.log('Checking Node.js...');
try {
  const version = execSync(`"${nodePath}" --version`, { encoding: 'utf-8' }).trim();
  console.log(`  Node.js ${version} found`);
} catch (error) {
  console.error('  Node.js not found at:', nodePath);
  console.error('  Please install Node.js from https://nodejs.org/');
  process.exit(1);
}

// Install dependencies
console.log('\nInstalling dependencies...');
try {
  execSync(`"${npmPath}" install`, { 
    cwd: rootDir,
    stdio: 'inherit' 
  });
  console.log('  Dependencies installed successfully');
} catch (error) {
  console.error('  Failed to install dependencies');
  process.exit(1);
}

console.log('\n=== Setup Complete ===');
console.log('\nNext steps:');
console.log('  1. cd apps/web && npm run dev     - Start Next.js frontend');
console.log('  2. cd apps/api && npm run dev      - Start Express API');
console.log('  3. cd services/python && python main.py  - Start FastAPI');
