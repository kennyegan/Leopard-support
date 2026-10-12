import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
 testDir:'./tests',fullyParallel:false,workers:1,timeout:45000,
 reporter:[['list'],['json',{outputFile:process.env.PLAYWRIGHT_REPORT || '../../docs/mvp/results/browser.json'}]],
 use:{reducedMotion:'reduce',baseURL:'http://127.0.0.1:3000',trace:'retain-on-failure',screenshot:'only-on-failure',
      ...devices['Desktop Chrome'],channel:'chrome'},
});
