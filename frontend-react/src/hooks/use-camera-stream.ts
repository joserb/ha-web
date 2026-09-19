import { useCallback, useEffect, useRef, useState } from "react";

export type CameraStatus = "idle" | "unsupported" | "connecting" | "live" | "reconnecting" | "error";

/**
 * Codec strings advertised to go2rtc, filtered by what this browser can
 * actually decode. The gateway picks the intersection with the camera's own
 * tracks, so asking for less here is how a browser without HEVC or FLAC still
 * gets the H.264/AAC it understands instead of an unplayable stream.
 */
const CODECS = [
  "avc1.640029", "avc1.64002A", "avc1.640033", // H.264
  "hvc1.1.6.L153.B0",                          // H.265
  "mp4a.40.2", "mp4a.40.5",                    // AAC
  "flac", "opus",
];

// A connection that produced no picture is a failure, however healthy the
// socket looks: the camera can accept RTSP and never send a keyframe.
const CONNECT_TIMEOUT_MS = 10_000;
const STALL_TIMEOUT_MS = 10_000;
const STALL_CHECK_MS = 2_000;
// Three attempts, then the user decides. An unattended retry loop against an
// unplugged camera would keep the Raspberry busy for as long as the tab lives.
const RETRY_DELAYS_MS = [1_000, 3_000, 5_000];
// Live video is worth nothing buffered: drop what playback already passed and
// jump forward when the browser falls behind after a stall.
const MAX_BUFFER_SECONDS = 30;
const MAX_DRIFT_SECONDS = 5;

function supportedCodecs(): string {
  return CODECS.filter((codec) => MediaSource.isTypeSupported(`video/mp4; codecs="${codec}"`)).join();
}

export function useCameraStream(path: string) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [status, setStatus] = useState<CameraStatus>(
    typeof MediaSource === "undefined" ? "unsupported" : "idle",
  );
  const [error, setError] = useState<string | null>(null);
  // Set when the widget stopped itself (hidden tab, scrolled away) rather than
  // by the user, so the card can offer Resume instead of pretending nothing
  // happened or starting video again without being asked.
  const [interrupted, setInterrupted] = useState(false);
  // Every session gets a number. Anything a previous socket, timer or
  // MediaSource callback does after being torn down is ignored by comparing
  // against it: a slow teardown must never take over a newer player.
  const session = useRef(0);
  const teardown = useRef<(() => void) | null>(null);
  const wanted = useRef(false);

  const close = useCallback(() => {
    session.current += 1;
    teardown.current?.();
    teardown.current = null;
  }, []);

  const connect = useCallback((attempt: number) => {
    if (typeof MediaSource === "undefined") return;
    close();
    const id = session.current;
    const alive = () => session.current === id;

    const video = videoRef.current;
    if (!video) return;

    setStatus(attempt === 0 ? "connecting" : "reconnecting");
    setError(null);

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}${path}`);
    socket.binaryType = "arraybuffer";

    const media = new MediaSource();
    const objectUrl = URL.createObjectURL(media);
    let buffer: SourceBuffer | null = null;
    const queue: ArrayBuffer[] = [];
    const timers: number[] = [];
    let playing = false;
    let lastTime = -1;
    let lastProgress = Date.now();

    const stop = () => {
      timers.forEach(clearTimeout);
      timers.forEach(clearInterval);
      socket.onclose = null;
      socket.close();
      // Detaching the element before revoking the URL keeps Chrome from
      // logging a decode error for the stream we are dismantling on purpose.
      video.removeAttribute("src");
      video.load();
      URL.revokeObjectURL(objectUrl);
    };
    teardown.current = stop;

    const fail = (reason: string) => {
      if (!alive()) return;
      stop();
      if (!wanted.current) return;
      const delay = RETRY_DELAYS_MS[attempt];
      if (delay === undefined) {
        // Out of attempts: the session is over and nothing is wanted until the
        // user presses Retry, so a hidden tab does not report it as paused.
        session.current += 1;
        wanted.current = false;
        setError(reason);
        setStatus("error");
        return;
      }
      setStatus("reconnecting");
      setError(reason);
      const retry = window.setTimeout(() => {
        if (session.current === id && wanted.current) connect(attempt + 1);
      }, delay);
      // The pending retry belongs to the session that scheduled it, so a Stop
      // in the meantime cancels it through the same teardown path.
      teardown.current = () => window.clearTimeout(retry);
    };

    const flush = () => {
      if (!buffer || buffer.updating || !queue.length) return;
      try {
        buffer.appendBuffer(queue.shift()!);
      } catch {
        fail("Playback buffer error");
      }
    };

    const trim = () => {
      if (!buffer || buffer.updating || !buffer.buffered.length) return;
      try {
        const end = buffer.buffered.end(buffer.buffered.length - 1);
        const start = buffer.buffered.start(0);
        if (end - start > MAX_BUFFER_SECONDS) buffer.remove(start, end - MAX_BUFFER_SECONDS / 2);
        if (end - video.currentTime > MAX_DRIFT_SECONDS) video.currentTime = end - 0.5;
      } catch { /* The buffer moved under us; the next segment retries. */ }
    };

    video.src = objectUrl;
    media.addEventListener("sourceopen", () => URL.revokeObjectURL(objectUrl), { once: true });

    socket.onopen = () => {
      if (!alive()) return;
      const codecs = supportedCodecs();
      if (!codecs) return fail("This browser cannot play the camera's format");
      socket.send(JSON.stringify({ type: "mse", value: codecs }));
    };

    socket.onmessage = (event) => {
      if (!alive()) return;
      if (typeof event.data !== "string") {
        queue.push(event.data as ArrayBuffer);
        flush();
        return;
      }
      const message = JSON.parse(event.data) as { type: string; value?: string };
      // The gateway reports a missing or unreachable source this way; without
      // it the socket would just sit open and time out with no explanation.
      if (message.type === "error") return fail(message.value ?? "Camera gateway error");
      if (message.type !== "mse" || !message.value) return;
      const mime = message.value;
      const addBuffer = () => {
        try {
          buffer = media.addSourceBuffer(mime);
          buffer.mode = "segments";
          buffer.addEventListener("updateend", () => { flush(); trim(); });
          flush();
        } catch {
          fail("Unsupported video format");
        }
      };
      if (media.readyState === "open") addBuffer();
      else media.addEventListener("sourceopen", addBuffer, { once: true });
      void video.play().catch(() => { /* Autoplay is muted; a refusal shows up as a stall. */ });
    };

    socket.onerror = () => fail("Camera connection failed");
    socket.onclose = () => fail(playing ? "Camera connection lost" : "Camera connection closed");

    timers.push(window.setTimeout(() => {
      if (!playing) fail("No video from the camera");
    }, CONNECT_TIMEOUT_MS));

    // Only moving playback counts as Live. A frozen last frame is exactly what
    // a camera viewer must not present as the current image.
    timers.push(window.setInterval(() => {
      if (!alive()) return;
      // A browser may pause playback on its own (autoplay policy, background
      // throttling). Asking it to resume is worth a try; if it does not, the
      // stall deadline below still fires instead of leaving a frozen frame.
      if (video.paused) void video.play().catch(() => { /* Handled by the stall deadline. */ });
      if (video.currentTime !== lastTime) {
        lastTime = video.currentTime;
        lastProgress = Date.now();
        if (!playing) {
          playing = true;
          setStatus("live");
          setError(null);
        }
        return;
      }
      if (playing && Date.now() - lastProgress > STALL_TIMEOUT_MS) fail("Video stalled");
    }, STALL_CHECK_MS));
  }, [close, path]);

  const start = useCallback(() => {
    wanted.current = true;
    setInterrupted(false);
    connect(0);
  }, [connect]);

  const halt = useCallback((byUser: boolean) => {
    const wasOn = wanted.current;
    wanted.current = false;
    close();
    setStatus(typeof MediaSource === "undefined" ? "unsupported" : "idle");
    setError(null);
    setInterrupted(!byUser && wasOn);
  }, [close]);

  const stop = useCallback(() => halt(true), [halt]);
  // Leaving the page open on a live stream is the one way this widget could
  // quietly cost bandwidth and Raspberry CPU all day, so anything that means
  // nobody is watching stops it and waits for a deliberate Resume.
  const suspend = useCallback(() => { if (wanted.current) halt(false); }, [halt]);

  useEffect(() => {
    const onHidden = () => { if (document.hidden) suspend(); };
    document.addEventListener("visibilitychange", onHidden);
    return () => document.removeEventListener("visibilitychange", onHidden);
  }, [suspend]);

  useEffect(() => () => { wanted.current = false; close(); }, [close]);

  return { videoRef, status, error, interrupted, start, stop, suspend };
}
