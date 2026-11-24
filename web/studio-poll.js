/** Poll only while the workspace is visible. Schedule after completion so slow requests never pile up. */
export function visiblePoll(task, delay, page = document, timers = globalThis) {
  let timer, running = false, enabled = false, wakePending = false;
  function schedule(ms) {
    timers.clearTimeout(timer);
    if (enabled && !page.hidden) timer = timers.setTimeout(run, ms);
  }
  async function run() {
    if (!enabled || page.hidden) return;
    if (running) { wakePending = true; return; }
    running = true;
    try { await task(); }
    finally {
      running = false;
      schedule(wakePending ? 0 : delay());
      wakePending = false;
    }
  }
  const wake = () => schedule(0);
  return {
    start() {
      if (enabled) return;
      enabled = true;
      page.addEventListener('visibilitychange', wake);
      schedule(delay());
    },
    stop() {
      enabled = false;
      page.removeEventListener('visibilitychange', wake);
      timers.clearTimeout(timer);
    },
    wake,
  };
}

// Full reconciliation also picks up nested files changed by external tools.
export function collectionDue({force, active, wasActive, pending, revision, previous, age}) {
  return force || !!active || !!wasActive || !!pending || revision !== previous || age >= 60000;
}

export function mergeCollection(records, delta, order = delta.order) {
  const byId = new Map((delta.full ? [] : records).map(job => [job.id, job]));
  for (const job of delta.changes) byId.set(job.id, job);
  for (const id of delta.unavailable) byId.delete(id);
  return order.map(id => byId.get(id)).filter(Boolean);
}
