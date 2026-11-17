const pointEpsilon = 1e-10;
const areaEpsilon = 1e-8;

function isPoint(point) {
    return Array.isArray(point) && point.length === 2 && point.every(Number.isFinite);
}

function inImage(point) {
    return isPoint(point) && point.every(value => value >= 0 && value <= 1);
}

export function polygonBounds(points) {
    if (!Array.isArray(points) || !points.length || !Array.from(points).every(isPoint)) return null;
    return points.reduce(([left, top, right, bottom], [x, y]) =>
        [Math.min(left, x), Math.min(top, y), Math.max(right, x), Math.max(bottom, y)],
    [Infinity, Infinity, -Infinity, -Infinity]);
}

export function mapPoint([a, b, c, d, e, f], [x, y]) {
    return [a * x + b * y + c, d * x + e * y + f];
}

export function scaleOverlay(transform, anchor, [width, height]) {
    const [a, b, , d, e] = transform;
    const [x, y] = mapPoint(transform, anchor);
    return [a * width, b * width, x - (a * anchor[0] + b * anchor[1]) * width,
        d * height, e * height, y - (d * anchor[0] + e * anchor[1]) * height];
}

export function fitOverlayRect([x0, y0, x1, y1], [left, top, right, bottom]) {
    const width = (right - left) / (x1 - x0), height = (bottom - top) / (y1 - y0);
    return [width, 0, left - width * x0, 0, height, top - height * y0];
}

export function fitLinkedAffine(source, target) {
    if (!Array.isArray(source) || !Array.isArray(target) || source.length !== 4 || target.length !== 4 ||
        ![0, 1, 2, 3].every(index => inImage(source[index]) && inImage(target[index]))) return null;
    const center = points => points.reduce(([x, y], [px, py]) => [x + px / 4, y + py / 4], [0, 0]);
    const [tx, ty] = center(target), [sx, sy] = center(source);
    const [left, top, right, bottom] = polygonBounds(target);
    const scaleX = Math.max(right - left, 1e-8), scaleY = Math.max(bottom - top, 1e-8);
    let xx = 0, xy = 0, yy = 0, xu = 0, yu = 0, xv = 0, yv = 0;
    for (let index = 0; index < 4; index++) {
        const x = (target[index][0] - tx) / scaleX, y = (target[index][1] - ty) / scaleY;
        const u = source[index][0] - sx, v = source[index][1] - sy;
        xx += x * x; xy += x * y; yy += y * y;
        xu += x * u; yu += y * u; xv += x * v; yv += y * v;
    }
    const scatterDet = xx * yy - xy * xy;
    const largerEigenvalue = (xx + yy + Math.hypot(xx - yy, 2 * xy)) / 2;
    // With four centered samples the constant column has squared norm four.
    if (!largerEigenvalue || scatterDet / largerEigenvalue < 4e-12) return null;
    const a = (yy * xu - xy * yu) / (scatterDet * scaleX), b = (xx * yu - xy * xu) / (scatterDet * scaleY);
    const d = (yy * xv - xy * yv) / (scatterDet * scaleX), e = (xx * yv - xy * xv) / (scatterDet * scaleY);
    const c = sx - a * tx - b * ty, f = sy - d * tx - e * ty;
    const det = a * e - b * d;
    if (det <= 1e-10 || (a * a + b * b + d * d + e * e) / det > 50 + 1 / 50) return null;
    const [sLeft, sTop, sRight, sBottom] = polygonBounds(source);
    const width = Math.max(sRight - sLeft, 1e-8), height = Math.max(sBottom - sTop, 1e-8);
    for (let index = 0; index < 4; index++) {
        const [x, y] = mapPoint([a, b, c, d, e, f], target[index]);
        if (Math.hypot((x - source[index][0]) / width, (y - source[index][1]) / height) > .12) return null;
    }
    // Projection samples model → reference. Preview uses the inverse.
    return [e / det, -b / det, (b * f - e * c) / det,
        -d / det, a / det, (d * c - a * f) / det];
}

const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
const distanceSquared = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
const within = (value, a, b) => Math.min(a, b) - pointEpsilon <= value && value <= Math.max(a, b) + pointEpsilon;
const onSegment = (p, a, b, side) => Math.abs(side) <= pointEpsilon &&
    within(p[0], a[0], b[0]) && within(p[1], a[1], b[1]);

function intersects(a, b, c, d) {
    const ac = cross(a, b, c), ad = cross(a, b, d), ca = cross(c, d, a), cb = cross(c, d, b);
    const opposite = (x, y) => x > pointEpsilon && y < -pointEpsilon || x < -pointEpsilon && y > pointEpsilon;
    return opposite(ac, ad) && opposite(ca, cb) ||
        onSegment(c, a, b, ac) || onSegment(d, a, b, ad) ||
        onSegment(a, c, d, ca) || onSegment(b, c, d, cb);
}

export function validatePolygon(points) {
    if (!Array.isArray(points) || points.length < 3 || points.length > 128 || !Array.from(points).every(inImage)) return false;
    let twiceArea = 0;
    for (let i = 0; i < points.length; i++) {
        const a = points[i], b = points[(i + 1) % points.length], c = points[(i + 2) % points.length];
        if (distanceSquared(a, b) <= pointEpsilon ** 2) return false;
        if (onSegment(c, a, b, cross(a, b, c)) || onSegment(a, b, c, cross(b, c, a))) return false;
        twiceArea += a[0] * b[1] - a[1] * b[0];
        for (let j = i + 2; j < points.length; j++) {
            if (i === 0 && j === points.length - 1) continue;
            if (intersects(a, b, points[j], points[(j + 1) % points.length])) return false;
        }
    }
    return Math.abs(twiceArea) > 2 * areaEpsilon;
}

function segmentDistanceSquared(point, a, b) {
    const length = distanceSquared(a, b);
    if (!length) return distanceSquared(point, a);
    const x = b[0] - a[0], y = b[1] - a[1];
    const t = Math.max(0, Math.min(1, ((point[0] - a[0]) * x + (point[1] - a[1]) * y) / length));
    return distanceSquared(point, [a[0] + x * t, a[1] + y * t]);
}

function simplifyOpen(points, tolerance) {
    const keep = new Set([0, points.length - 1]);
    const segments = [[0, points.length - 1]];
    while (segments.length) {
        const [start, end] = segments.pop();
        let farthest = null, error = tolerance ** 2;
        for (let i = start + 1; i < end; i++) {
            const distance = segmentDistanceSquared(points[i], points[start], points[end]);
            if (distance > error) { farthest = i; error = distance; }
        }
        if (farthest !== null) {
            keep.add(farthest);
            segments.push([start, farthest], [farthest, end]);
        }
    }
    return points.filter((_, index) => keep.has(index));
}

export function simplifyLasso(points, max = 128) {
    const trace = [];
    for (const point of points) {
        if (inImage(point) && (!trace.length || distanceSquared(point, trace.at(-1)) > 1e-10)) trace.push(point);
    }
    if (trace.length > 1 && distanceSquared(trace[0], trace.at(-1)) <= 1e-10) trace.pop();
    if (trace.length <= 3) return trace;
    // Split the closed outline into two open paths far from the closing edge.
    let split = 1;
    for (let i = 2; i < trace.length; i++) {
        if (distanceSquared(trace[0], trace[i]) > distanceSquared(trace[0], trace[split])) split = i;
    }
    const first = trace.slice(0, split + 1), second = [...trace.slice(split), trace[0]];
    const simplify = tolerance => [...simplifyOpen(first, tolerance).slice(0, -1), ...simplifyOpen(second, tolerance).slice(0, -1)];
    const budget = Math.max(3, Math.min(128, Math.floor(max)));
    let tolerance = .00065;
    let outline = simplify(tolerance);
    while (outline.length > budget) {
        tolerance *= 1.5;
        outline = simplify(tolerance);
    }
    if (outline.length < 3 && trace.length <= budget) return trace;
    return outline;
}
