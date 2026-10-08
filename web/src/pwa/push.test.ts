import { describe, expect, it } from "vitest";
import { fakeApi } from "../test/fakeApi.ts";
import { fakePushEnv, fakeSubscription, KEY_BYTES } from "../test/fakePush.ts";
import {
  base64UrlToBytes,
  browserPushEnv,
  disablePush,
  enablePush,
  pushStatus,
  refreshPush,
  subscriptionBody,
} from "./push.ts";

describe("browserPushEnv", () => {
  const worker = { getRegistration: () => Promise.resolve(undefined) };
  const notification = {
    permission: "default" as const,
    requestPermission: () => Promise.resolve("default" as const),
  };

  it("detects a Home Screen app with push", () => {
    const env = browserPushEnv({
      matchMedia: (query) => ({ matches: query === "(display-mode: standalone)" }),
      Notification: notification,
      PushManager: function PushManager() {
        // A stand-in; only its presence matters.
      },
      navigator: { serviceWorker: worker },
    });

    expect(env).toEqual({ standalone: true, notification, serviceWorker: worker });
  });

  it("knows the older iOS standalone flag and browsers without push", () => {
    expect(browserPushEnv({ navigator: { standalone: true } })).toEqual({
      standalone: true,
      notification: undefined,
      serviceWorker: undefined,
    });
    const tab = browserPushEnv({
      matchMedia: () => ({ matches: false }),
      navigator: { serviceWorker: worker },
    });
    expect(tab.standalone).toBe(false);
    expect(tab.serviceWorker).toBeUndefined();
  });
});

describe("pushStatus", () => {
  it("asks to install first in a browser tab without push", async () => {
    expect(await pushStatus(fakePushEnv({ standalone: false, push: false }).env)).toBe("install");
    expect(await pushStatus(fakePushEnv({ standalone: false, notification: false }).env)).toBe(
      "install",
    );
  });

  it("is unsupported when installed but without push", async () => {
    expect(await pushStatus(fakePushEnv({ push: false }).env)).toBe("unsupported");
    expect(await pushStatus(fakePushEnv({ notification: false }).env)).toBe("unsupported");
  });

  it("is off while the worker is still registering", async () => {
    expect(await pushStatus(fakePushEnv({ permission: "granted", registered: false }).env)).toBe(
      "off",
    );
  });

  it("follows the permission and the subscription", async () => {
    expect(await pushStatus(fakePushEnv({ permission: "denied" }).env)).toBe("denied");
    expect(await pushStatus(fakePushEnv().env)).toBe("off");
    expect(await pushStatus(fakePushEnv({ permission: "granted" }).env)).toBe("off");
    const subscription = fakeSubscription();
    expect(await pushStatus(fakePushEnv({ permission: "granted", subscription }).env)).toBe("on");
  });
});

describe("enablePush", () => {
  it("asks, subscribes with the daemon key and registers the subscription", async () => {
    const { env, manager, requestPermission } = fakePushEnv();
    const api = fakeApi();

    expect(await enablePush(env, api)).toBe("on");

    expect(requestPermission).toHaveBeenCalled();
    expect(manager.subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: new Uint8Array(KEY_BYTES),
    });
    expect(api.subscribePush).toHaveBeenCalledWith({
      endpoint: "https://push/new",
      keys: { p256dh: "p", auth: "a" },
    });
  });

  it("reuses a subscription made with the same key", async () => {
    const subscription = fakeSubscription();
    const { env, manager } = fakePushEnv({ permission: "granted", subscription });
    const api = fakeApi();

    expect(await enablePush(env, api)).toBe("on");

    expect(manager.subscribe).not.toHaveBeenCalled();
    expect(api.subscribePush).toHaveBeenCalledWith(subscriptionBody(subscription));
  });

  it("replaces a subscription made with another key", async () => {
    for (const key of [
      [9, 9, 9],
      [4, 1],
    ]) {
      const subscription = fakeSubscription(key);
      const { env, manager } = fakePushEnv({ subscription });

      expect(await enablePush(env, fakeApi())).toBe("on");
      expect(subscription.unsubscribe).toHaveBeenCalled();
      expect(manager.subscribe).toHaveBeenCalled();
    }
    const keyless = { ...fakeSubscription(), options: { applicationServerKey: null } };
    const { env, manager } = fakePushEnv({ subscription: keyless });
    await enablePush(env, fakeApi());
    expect(manager.subscribe).toHaveBeenCalled();
  });

  it("stops when the user declines or dismisses the prompt", async () => {
    const api = fakeApi();

    expect(await enablePush(fakePushEnv({ answer: "denied" }).env, api)).toBe("denied");
    expect(await enablePush(fakePushEnv({ answer: "default" }).env, api)).toBe("off");
    expect(api.vapidKey).not.toHaveBeenCalled();
  });

  it("reports why push cannot work instead of subscribing", async () => {
    expect(
      await enablePush(fakePushEnv({ standalone: false, notification: false }).env, fakeApi()),
    ).toBe("install");
    await expect(enablePush(fakePushEnv({ registered: false }).env, fakeApi())).rejects.toThrow(
      "still setting up",
    );
  });
});

describe("refreshPush", () => {
  it("sends this device's subscription again when notifications are on here", async () => {
    const subscription = fakeSubscription();
    const { env, manager, requestPermission } = fakePushEnv({
      permission: "granted",
      subscription,
    });
    const api = fakeApi();

    await refreshPush(env, api);

    expect(requestPermission).not.toHaveBeenCalled();
    expect(manager.subscribe).not.toHaveBeenCalled();
    expect(api.subscribePush).toHaveBeenCalledWith(subscriptionBody(subscription));
  });

  it("renews a subscription made with the daemon's old key", async () => {
    const subscription = fakeSubscription([9, 9, 9]);
    const { env, manager } = fakePushEnv({ permission: "granted", subscription });
    const api = fakeApi();

    await refreshPush(env, api);

    expect(subscription.unsubscribe).toHaveBeenCalled();
    expect(manager.subscribe).toHaveBeenCalled();
    expect(api.subscribePush).toHaveBeenCalledWith({
      endpoint: "https://push/new",
      keys: { p256dh: "p", auth: "a" },
    });
  });

  it("leaves turning notifications on to the user", async () => {
    const api = fakeApi();
    const subscription = fakeSubscription();

    await refreshPush(fakePushEnv({ subscription }).env, api);
    await refreshPush(fakePushEnv({ permission: "granted" }).env, api);
    await refreshPush(fakePushEnv({ permission: "granted", registered: false }).env, api);
    await refreshPush(fakePushEnv({ notification: false }).env, api);

    expect(api.vapidKey).not.toHaveBeenCalled();
    expect(api.subscribePush).not.toHaveBeenCalled();
  });
});

describe("disablePush", () => {
  it("unregisters from the daemon and unsubscribes", async () => {
    const subscription = fakeSubscription();
    const api = fakeApi();

    expect(await disablePush(fakePushEnv({ subscription }).env, api)).toBe("off");

    expect(api.unsubscribePush).toHaveBeenCalledWith("https://push/1");
    expect(subscription.unsubscribe).toHaveBeenCalled();
  });

  it("has nothing to do without a subscription or worker", async () => {
    const api = fakeApi();

    expect(await disablePush(fakePushEnv().env, api)).toBe("off");
    expect(await disablePush(fakePushEnv({ push: false }).env, api)).toBe("off");
    expect(api.unsubscribePush).not.toHaveBeenCalled();
  });
});

describe("encoding", () => {
  it("decodes base64url keys", () => {
    expect([...base64UrlToBytes("BAEC")]).toEqual(KEY_BYTES);
    expect([...base64UrlToBytes("-_8")]).toEqual([251, 255]);
  });

  it("refuses subscriptions without keys", () => {
    const bare = { ...fakeSubscription(), toJSON: () => ({ endpoint: "https://push/1" }) };
    expect(() => subscriptionBody(bare)).toThrow("no push keys");
    const partial = {
      ...fakeSubscription(),
      toJSON: () => ({ endpoint: "https://p", keys: { auth: "a" } }),
    };
    expect(() => subscriptionBody(partial)).toThrow("no push keys");
    const nowhere = { ...fakeSubscription(), toJSON: () => ({ keys: { p256dh: "p", auth: "a" } }) };
    expect(() => subscriptionBody(nowhere)).toThrow("no push keys");
  });
});
