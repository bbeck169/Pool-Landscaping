/**
 * Phase 52.1c · Feb-2026 — Global jest auto-mock for react-native-webrtc.
 *
 * The real module imports NativeEventEmitter at load-time, which is
 * null under jest-expo. Any test that transitively imports the mobile
 * walkie channel page (`app/walkie/[channelId].tsx`) would otherwise
 * blow up at collection. This mock stubs every export the LivePanel
 * touches — individual tests can jest.mock() override for behavior
 * assertions.
 */
class _RTCPeerConnection {
  constructor(cfg) { this._cfg = cfg; this._handlers = {}; }
  addTrack() {}
  createOffer = async () => ({ type: "offer", sdp: "OFFER-SDP" });
  createAnswer = async () => ({ type: "answer", sdp: "ANSWER-SDP" });
  setLocalDescription = async () => {};
  setRemoteDescription = async () => {};
  addIceCandidate = async () => {};
  close = () => {};
  set onicecandidate(fn) { this._handlers.ice = fn; }
  set ontrack(fn) { this._handlers.track = fn; }
}

class _RTCSessionDescription {
  constructor(init) { Object.assign(this, init); }
}
class _RTCIceCandidate {
  constructor(init) { Object.assign(this, init); }
}

module.exports = {
  RTCPeerConnection: _RTCPeerConnection,
  RTCSessionDescription: _RTCSessionDescription,
  RTCIceCandidate: _RTCIceCandidate,
  mediaDevices: {
    getUserMedia: async () => ({
      getAudioTracks: () => [{ enabled: false, stop: () => {} }],
      getTracks: () => [{ enabled: false, stop: () => {} }],
    }),
  },
  registerGlobals: () => {},
};
