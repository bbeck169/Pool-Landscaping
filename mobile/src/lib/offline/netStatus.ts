/**
 * Feb-2026 · Phase 1 offline foundation — connectivity + freshness.
 *
 * ``useOnline()`` — subscribes to ``@react-native-community/netinfo``
 * and returns a live ``true / false``.  During the initial fetch it
 * assumes ``true`` (optimistic) so first-render doesn't flash the
 * offline badge on a slow radio.
 *
 * ``markApiSuccess()`` / ``getSecondsSinceLastSuccess()`` — module-
 * level clock the api wrapper pings on every successful 2xx round-
 * trip.  Consumers can use this to render a "stale — using cache"
 * hint when connectivity is nominally up but real requests are
 * failing.
 */
import { useEffect, useState } from "react";
import NetInfo from "@react-native-community/netinfo";


let _lastSuccessAt = Date.now();

export function markApiSuccess(): void {
  _lastSuccessAt = Date.now();
}

export function getSecondsSinceLastSuccess(): number {
  return Math.floor((Date.now() - _lastSuccessAt) / 1000);
}


export function useOnline(): boolean {
  const [online, setOnline] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    // Prime the initial value.
    NetInfo.fetch().then((state) => {
      if (!mounted) return;
      // ``isConnected`` can be ``null`` mid-transition — treat as
      // online to avoid a false-offline flash.
      setOnline(state.isConnected !== false);
    }).catch(() => { /* stay optimistic */ });

    const unsub = NetInfo.addEventListener((state) => {
      if (!mounted) return;
      setOnline(state.isConnected !== false);
    });
    return () => { mounted = false; unsub(); };
  }, []);

  return online;
}
