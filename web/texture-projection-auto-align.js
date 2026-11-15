const GRID = 80;
const ALPHA_THRESHOLD = 64;
const MAX_SAMPLES = 320;
const SEARCH_MS = 6500;
const PI_OVER_180 = Math.PI / 180;
const degrees = (angle) => ((angle + 180) % 360 + 360) % 360 - 180;
const limited = (value, min, max) => Math.max(min, Math.min(max, value));
const yieldToPage = () => new Promise((resolve) => setTimeout(resolve, 0));

function describeSilhouette({ data, width, height }) {
    let left = width, top = height, right = 0, bottom = 0;
    let foreground = 0, transparent = 0;
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const alpha = data[(y * width + x) * 4 + 3];
            if (alpha <= ALPHA_THRESHOLD) {
                transparent++;
                continue;
            }
            foreground++;
            left = Math.min(left, x);
            top = Math.min(top, y);
            right = Math.max(right, x + 1);
            bottom = Math.max(bottom, y + 1);
        }
    }
    if (foreground < 16 || transparent < Math.max(8, width * height * 0.01)) return null;
    const spanX = right - left, spanY = bottom - top;
    if (spanX < 3 || spanY < 3) return null;
    const scale = Math.max(spanX, spanY) / (GRID - 4);
    const originX = (left + right) / 2 - (GRID * scale) / 2;
    const originY = (top + bottom) / 2 - (GRID * scale) / 2;
    const alpha = new Float32Array(GRID * GRID);
    const redGreen = new Float32Array(GRID * GRID);
    const blueYellow = new Float32Array(GRID * GRID);
    for (let y = 0; y < GRID; y++) {
        const py = originY + (y + .5) * scale - .5;
        const sy = Math.floor(py);
        const fy = py - sy;
        for (let x = 0; x < GRID; x++) {
            const px = originX + (x + .5) * scale - .5;
            const sx = Math.floor(px);
            const fx = px - sx;
            let covered = 0, red = 0, green = 0, blue = 0;
            for (let dy = 0; dy < 2; dy++) {
                for (let dx = 0; dx < 2; dx++) {
                    const ix = sx + dx, iy = sy + dy;
                    if (ix < 0 || iy < 0 || ix >= width || iy >= height) continue;
                    const p = (iy * width + ix) * 4;
                    const weight = (dx ? fx : 1 - fx) * (dy ? fy : 1 - fy) * data[p + 3] / 255;
                    covered += weight;
                    red += data[p] * weight;
                    green += data[p + 1] * weight;
                    blue += data[p + 2] * weight;
                }
            }
            const i = y * GRID + x;
            alpha[i] = limited((covered - .15) / .7, 0, 1);
            const denominator = red + green + blue + 60 * covered;
            if (denominator > 0) {
                redGreen[i] = (red - green) / denominator;
                blueYellow[i] = (2 * blue - red - green) / denominator;
            }
        }
    }
    return { alpha, colors: [redGreen, blueYellow] };
}

export function readReferenceSilhouette(imageData) {
    const silhouette = describeSilhouette(imageData);
    if (!silhouette) throw new Error('Auto Align needs a cutout with a transparent background. Choose Cutout reference or upload a transparent PNG.');
    return silhouette;
}

function compare(reference, candidate) {
    let intersection = 0, union = 0;
    for (let i = 0; i < reference.alpha.length; i++) {
        intersection += Math.min(reference.alpha[i], candidate.alpha[i]);
        union += Math.max(reference.alpha[i], candidate.alpha[i]);
    }
    const silhouette = union ? intersection / union : 0;
    let color = 0, channels = 0;
    for (let channel = 0; channel < reference.colors.length; channel++) {
        const source = reference.colors[channel], target = candidate.colors[channel];
        let count = 0, sumSource = 0, sumTarget = 0, sqSource = 0, sqTarget = 0, products = 0;
        for (let i = 0; i < source.length; i++) {
            if (reference.alpha[i] < .95 || candidate.alpha[i] < .95) continue;
            const a = source[i], b = target[i];
            count++;
            sumSource += a;
            sumTarget += b;
            sqSource += a * a;
            sqTarget += b * b;
            products += a * b;
        }
        if (count < 64) continue;
        const spreadSource = sqSource - sumSource * sumSource / count;
        const spreadTarget = sqTarget - sumTarget * sumTarget / count;
        if (Math.min(spreadSource, spreadTarget) / count < .035 ** 2) continue;
        color += limited((products - sumSource * sumTarget / count) / Math.sqrt(spreadSource * spreadTarget), -1, 1);
        channels++;
    }
    // Color structure can break a tie between silhouettes. Color alone gets limited weight.
    const appearance = channels ? color / channels : 0;
    const score = silhouette * (1 + .045 * appearance) / 1.045;
    return { silhouette, appearance, score };
}

function poseAt(base, changes) {
    const pose = { ...base, ...changes, view: 'custom' };
    pose.yaw = degrees(pose.yaw);
    pose.pitch = limited(pose.pitch, -90, 90);
    pose.roll = degrees(pose.roll);
    pose.fov = limited(pose.fov, 12, 90);
    if (pose.roll === 0) {
        if (pose.yaw === 0) pose.view = ({ '-90': 'bottom', 0: 'front', 90: 'top' })[pose.pitch] || 'custom';
        if (pose.pitch === 0) pose.view = ({ '-180': 'back', '-90': 'left', 0: 'front', 90: 'right' })[pose.yaw] || 'custom';
    }
    return pose;
}

function direction(pose) {
    const yaw = pose.yaw * PI_OVER_180, pitch = pose.pitch * PI_OVER_180;
    return [Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)];
}

function separate(a, b, cosine, rollLimit) {
    return a.direction.reduce((sum, value, index) => sum + value * b.direction[index], 0) < cosine
        || Math.abs(degrees(a.pose.roll - b.pose.roll)) >= rollLimit;
}

function bestDirections(entries, count, spacing) {
    const result = [];
    const cosine = Math.cos(spacing * PI_OVER_180);
    for (const candidate of [...entries].sort((a, b) => b.score - a.score)) {
        if (result.every((other) => separate(other, candidate, cosine, 35))) result.push(candidate);
        if (result.length === count) break;
    }
    return result;
}

export async function matchTextureProjectionCamera(reference, render, initialPose, { signal, onProgress } = {}) {
    const started = performance.now();
    let lastYield = started, tested = 0, limitedByTime = false;
    const candidates = new Map();
    const lenses = ['orthographic', 'perspective'];
    const progress = (total = MAX_SAMPLES) => onProgress?.({ tested, total });

    async function evaluate(pose) {
        signal?.throwIfAborted();
        const key = [pose.yaw, pose.pitch, pose.roll, pose.projection,
            pose.projection === 'perspective' ? pose.fov : 0].join(',');
        if (candidates.has(key)) return candidates.get(key);
        if (tested >= MAX_SAMPLES) return null;
        if (tested && performance.now() - started >= SEARCH_MS) {
            limitedByTime = true;
            return null;
        }
        if (performance.now() - lastYield >= 24) {
            progress();
            await yieldToPage();
            signal?.throwIfAborted();
            lastYield = performance.now();
        }
        const thumbnail = describeSilhouette(render(pose));
        const metrics = thumbnail ? compare(reference, thumbnail) : { score: 0, silhouette: 0, appearance: 0 };
        const result = { ...metrics, pose, direction: direction(pose) };
        candidates.set(key, result);
        tested++;
        return result;
    }

    progress();
    await yieldToPage();
    const initial = await evaluate(poseAt(initialPose, {}));
    const coarse = { ...initialPose, fov: 35 };
    const around = [0, 180, 90, -90, 30, -30, 150, -150, 60, -60, 120, -120];
    for (const pitch of [0, -28, 28, -58, 58, -90, 90]) {
        const offsets = Math.abs(pitch) === 90 ? [0] : Math.abs(pitch) > 30 ? around.slice(0, 4) : around;
        for (const offset of offsets) {
            if (limitedByTime) break;
            for (const projection of lenses) {
                await evaluate(poseAt(coarse, { yaw: coarse.yaw + offset, pitch, projection }));
            }
        }
    }
    const searchedCoarse = !limitedByTime;

    const coarseLeads = bestDirections(candidates.values(), 4, 33);
    for (const [rank, { pose }] of coarseLeads.entries()) {
        if (limitedByTime) break;
        for (const yaw of [-15, 0, 15]) {
            for (const pitch of [-14, 0, 14]) {
                const direction = { yaw: pose.yaw + yaw, pitch: pose.pitch + pitch };
                await evaluate(poseAt(pose, direction));
                if (rank < 2) {
                    for (const roll of [-8, 8]) await evaluate(poseAt(pose, { ...direction, roll: pose.roll + roll }));
                }
            }
        }
        for (const roll of [-24, 24, -12, 12]) await evaluate(poseAt(pose, { roll: pose.roll + roll }));
        for (const fov of [18, 60]) await evaluate(poseAt(pose, { fov, projection: 'perspective' }));
    }

    for (const step of [7, 3, 1.5]) {
        const leaders = bestDirections(candidates.values(), 3, 25);
        for (const [rank, { pose }] of leaders.entries()) {
            if (limitedByTime) break;
            for (const sign of [-1, 1]) {
                await evaluate(poseAt(pose, { yaw: pose.yaw + sign * step }));
                await evaluate(poseAt(pose, { pitch: pose.pitch + sign * step }));
                await evaluate(poseAt(pose, { roll: pose.roll + sign * step }));
                if (rank === 0) {
                    for (const slope of [-1, 1]) {
                        await evaluate(poseAt(pose, { yaw: pose.yaw + sign * step, pitch: pose.pitch + slope * step }));
                    }
                }
                if (pose.projection === 'perspective') await evaluate(poseAt(pose, { fov: pose.fov + sign * step * 2 }));
            }
        }
    }
    signal?.throwIfAborted();
    const [best, alternate] = bestDirections(candidates.values(), 2, 37);
    const ambiguous = Boolean(alternate && best.score - alternate.score < .022
        && Math.abs(best.silhouette - alternate.silhouette) < .035);
    const gain = best.score - initial.score;
    let reason = 'matched';
    if (!searchedCoarse) reason = 'time-limit';
    else if (best.silhouette < .63) reason = 'low-overlap';
    else if (ambiguous) reason = 'ambiguous';
    else if (gain < .018) reason = 'close';
    progress(tested);
    return {
        pose: best.pose, score: best.score, silhouette: best.silhouette,
        initialScore: initial.score, initialSilhouette: initial.silhouette,
        ambiguous, applied: reason === 'matched', reason,
    };
}
