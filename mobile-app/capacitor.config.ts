import type { CapacitorConfig } from "@capacitor/cli";

const appName = process.env.MOBILE_APP_NAME || "Technological World";
const appId = process.env.MOBILE_APP_ID || "com.technologicalworld.comercial";
const remoteUrl =
  process.env.MOBILE_APP_URL || "https://cotizaciones-solutec-production.up.railway.app/login";

const config: CapacitorConfig = {
  appId,
  appName,
  webDir: "web",
  bundledWebRuntime: false,
  server: {
    url: remoteUrl,
    cleartext: false,
    androidScheme: "https",
  },
  android: {
    allowMixedContent: false,
  },
  ios: {
    contentInset: "automatic",
  },
};

export default config;
