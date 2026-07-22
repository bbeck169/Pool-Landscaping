import { api } from "@/src/api";

export const registerPushToken = (token: string, platform?: string, deviceName?: string) =>
  api.post("/mobile-tokens", {
    token,
    platform: platform || null,
    device_name: deviceName || null,
  });

export const deletePushToken = (token: string) =>
  api.del(`/mobile-tokens?token=${encodeURIComponent(token)}`);

export const getMyTokens = () =>
  api.get("/mobile-tokens/mine");
