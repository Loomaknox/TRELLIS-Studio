import assert from 'node:assert/strict';
import test from 'node:test';
import { matchTextureProjectionCamera, readReferenceSilhouette } from '../web/texture-projection-auto-align.js';

const front = { view: 'front', projection: 'orthographic', yaw: 0, pitch: 0, roll: 0, fov: 35 };

function rectangle(width, height, x0, y0, x1, y1) {
    const data = new Uint8ClampedArray(width * height * 4);
    for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) data.set([180, 115, 75, 255], (y * width + x) * 4);
    }
    return { data, width, height };
}

function box([x0, y0, z0], [x1, y1, z1], shades) {
    const vertices = [[x0, y0, z0], [x0, y0, z1], [x0, y1, z0], [x0, y1, z1],
        [x1, y0, z0], [x1, y0, z1], [x1, y1, z0], [x1, y1, z1]];
    const faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]];
    return faces.flatMap((verticesOnFace, face) => [[0, 1, 2], [0, 2, 3]].map((triangle) => ({
        positions: triangle.map((i) => vertices[verticesOnFace[i]]), color: [...shades[face], 255],
    })));
}

const brass = [[112, 75, 45], [131, 105, 76], [75, 67, 37], [148, 93, 56], [88, 123, 125], [172, 80, 70]];
const teal = [[57, 114, 132], [131, 105, 76], [75, 67, 37], [83, 147, 158], [72, 128, 117], [81, 64, 82]];
const fixture = [
    ...box([-1.2, -.6, -.65], [1.2, .15, .65], brass),
    ...box([-.65, .12, -.55], [-.13, 1.1, -.05], teal),
    ...box([.71, -.55, -.95], [1.2, .49, -.15], brass),
    ...box([-.96, -.6, .31], [-.87, .55, .43], teal),
];

function renderFixture(pose, size = 96) {
    const [yaw, pitch, roll] = [pose.yaw, pose.pitch, pose.roll].map((value) => value * Math.PI / 180);
    const outward = [Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)];
    const horizontal = [Math.cos(yaw), 0, -Math.sin(yaw)];
    const vertical = [-Math.sin(yaw) * Math.sin(pitch), Math.cos(pitch), -Math.cos(yaw) * Math.sin(pitch)];
    const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
    const lens = Math.tan(pose.fov * Math.PI / 360);
    const isPerspective = pose.projection === 'perspective';
    const center = [0, .25, -.15];
    const project = (point) => {
        const p = point.map((value, i) => value - center[i]);
        const x = dot(p, horizontal), y = dot(p, vertical), z = dot(p, outward);
        const depth = 1.1 + 1.55 / lens - z;
        const scale = isPerspective ? 1 / (depth * lens) : .57;
        return [size * (.5 + .5 * scale * (x * Math.cos(roll) + y * Math.sin(roll))),
            size * (.5 - .5 * scale * (-x * Math.sin(roll) + y * Math.cos(roll))),
            isPerspective ? 1 / depth : z];
    };
    const data = new Uint8ClampedArray(size * size * 4);
    const depth = new Float64Array(size * size).fill(-Infinity);
    for (const { positions, color } of fixture) {
        const [a, b, c] = positions.map(project);
        const ux = b[0] - a[0], uy = b[1] - a[1], vx = c[0] - a[0], vy = c[1] - a[1];
        const determinant = ux * vy - uy * vx;
        if (Math.abs(determinant) < 1e-6) continue;
        const left = Math.max(0, Math.floor(Math.min(a[0], b[0], c[0])));
        const right = Math.min(size, Math.ceil(Math.max(a[0], b[0], c[0])));
        const top = Math.max(0, Math.floor(Math.min(a[1], b[1], c[1])));
        const bottom = Math.min(size, Math.ceil(Math.max(a[1], b[1], c[1])));
        for (let y = top; y < bottom; y++) {
            for (let x = left; x < right; x++) {
                const dx = x + .5 - a[0], dy = y + .5 - a[1];
                const u = (dx * vy - dy * vx) / determinant;
                const v = (dy * ux - dx * uy) / determinant;
                if (u < 0 || v < 0 || u + v > 1) continue;
                const z = a[2] + u * (b[2] - a[2]) + v * (c[2] - a[2]);
                const i = y * size + x;
                if (z <= depth[i]) continue;
                depth[i] = z;
                data.set(color, i * 4);
            }
        }
    }
    return { data, width: size, height: size };
}

test('finds the oblique perspective camera on an asymmetric textured fixture', async () => {
    const wanted = { ...front, view: 'custom', projection: 'perspective', yaw: -139, pitch: -9, roll: 6 };
    const reference = readReferenceSilhouette(renderFixture(wanted, 160));
    const progress = [];
    const result = await matchTextureProjectionCamera(reference, renderFixture, front, { onProgress: (value) => progress.push(value) });
    assert.equal(result.applied, true, JSON.stringify(result));
    assert.equal(result.ambiguous, false);
    assert.equal(result.pose.projection, 'perspective');
    assert.ok(Math.abs(result.pose.yaw - wanted.yaw) < 12, JSON.stringify(result));
    assert.ok(Math.abs(result.pose.pitch - wanted.pitch) < 10, JSON.stringify(result));
    assert.ok(result.silhouette > .88 && result.silhouette > result.initialSilhouette + .12, JSON.stringify(result));
    assert.equal(progress[0].tested, 0);
    assert.equal(progress.at(-1).tested, progress.at(-1).total);
    assert.ok(progress.at(-1).tested <= 320);
});

test('identical silhouettes and flat color leave direction ambiguous', async () => {
    const reference = readReferenceSilhouette(rectangle(100, 90, 10, 25, 70, 55));
    const result = await matchTextureProjectionCamera(reference, () => rectangle(96, 96, 24, 32, 72, 56), front);
    assert.equal(result.ambiguous, true);
    assert.equal(result.applied, false);
    assert.equal(result.reason, 'ambiguous');
    assert.ok(result.silhouette > .96);
});

test('distinct surface colors can distinguish the rear from an identical front silhouette', async () => {
    function render(pose) {
        const yaw = Math.abs(pose.yaw);
        const axisAligned = Math.abs(pose.pitch) < 8 && Math.abs(pose.roll) < 8 && (yaw < 8 || yaw > 172);
        const edge = axisAligned ? 18 : 34;
        const image = rectangle(96, 96, edge, 20, 96 - edge, 76);
        const colors = yaw > 90 ? [[160, 50, 70], [55, 85, 220]] : [[55, 85, 220], [160, 50, 70]];
        for (let y = 20; y < 76; y++) {
            for (let x = edge; x < 96 - edge; x++) image.data.set(colors[Number(x >= 48)], (y * 96 + x) * 4);
        }
        return image;
    }
    const reference = readReferenceSilhouette(render({ ...front, view: 'back', yaw: -180 }));
    const result = await matchTextureProjectionCamera(reference, render, front);
    assert.equal(result.applied, true);
    assert.equal(result.pose.view, 'back');
    assert.equal(result.silhouette, 1);
    assert.equal(result.initialSilhouette, 1);
});

test('retains differences in aspect ratio and rejects an opaque background', async () => {
    assert.throws(() => readReferenceSilhouette(rectangle(100, 90, 0, 0, 100, 90)), /transparent background/);
    const reference = readReferenceSilhouette(rectangle(100, 90, 10, 25, 90, 45));
    const result = await matchTextureProjectionCamera(reference, () => rectangle(96, 96, 32, 20, 52, 90), front);
    assert.equal(result.applied, false);
    assert.equal(result.reason, 'low-overlap');
    assert.ok(result.silhouette < .3);
});

test('aborts between rendered candidates', async () => {
    const image = rectangle(96, 96, 32, 20, 52, 90);
    const reference = readReferenceSilhouette(image);
    const controller = new AbortController();
    let renders = 0;
    await assert.rejects(matchTextureProjectionCamera(reference, () => {
        renders++;
        controller.abort();
        return image;
    }, front, { signal: controller.signal }), { name: 'AbortError' });
    assert.equal(renders, 1);
});
