import assert from 'node:assert/strict';
import {test} from 'node:test';
import {fitLinkedAffine, fitOverlayRect, mapPoint, polygonBounds, scaleOverlay, simplifyLasso, validatePolygon}
    from '../web/texture-projection-geometry.js';

const face = [[.483, .067], [.519, .066], [.501, .088], [.502, .102]];
const transform = [1.15, -.09, -.060, .12, .82, .030];

test('independent overlay resizing keeps the opposite edge and matches rectangular baking', () => {
    const source = [.2, .1, .8, .7];
    const before = [.3, .2, .7, .6];
    const anchor = [.5, source[1]];
    const placement = fitOverlayRect(source, before);
    const resized = scaleOverlay(placement, anchor, [1, 1.5]);
    const points = [[source[0], source[1]], [source[2], source[1]], [source[2], source[3]], [source[0], source[3]]];
    const expected = [.3, .2, .7, .8];
    assert.deepEqual(mapPoint(resized, anchor), mapPoint(placement, anchor));
    polygonBounds(points.map(point => mapPoint(resized, point))).forEach((value, index) => {
        assert.ok(Math.abs(value - expected[index]) < 1e-10);
    });
    const bakedPlacement = fitOverlayRect(source, expected);
    points.forEach(point => {
        const [x, y] = mapPoint(resized, point);
        const [bakedX, bakedY] = mapPoint(bakedPlacement, point);
        assert.ok(Math.hypot(x - bakedX, y - bakedY) < 1e-10);
    });
});

test('guides align a small selection outside their hull with one shared mapping', () => {
    const target = face.map(point => mapPoint(transform, point));
    const fit = fitLinkedAffine(face, target);
    assert.ok(fit);
    const selection = [[.489, .108], [.508, .109], [.505, .114], [.490, .114]];
    for (const point of selection) {
        const expected = mapPoint(transform, point), actual = mapPoint(fit, point);
        assert.ok(Math.hypot(expected[0] - actual[0], expected[1] - actual[1]) < 1e-10);
    }
});

test('missing, mirrored, collapsed and mismatched pairs are detected', () => {
    const mirror = face.map(([x, y]) => [1 - x, y]);
    const collapsed = face.map(([x]) => [x, .5]);
    const mismatched = [face[0], face[1], face[3], face[2]];
    assert.equal(fitLinkedAffine(face.slice(0, 3), face), null);
    assert.equal(fitLinkedAffine(face, mirror), null);
    assert.equal(fitLinkedAffine(face, collapsed), null);
    assert.equal(fitLinkedAffine(face, mismatched), null);
});

test('a concave outline is valid while crossing edges, folds and out-of-frame vertices are rejected', () => {
    const outline = [[.15, .15], [.8, .15], [.8, .7], [.55, .4], [.15, .7]];
    assert.equal(validatePolygon(outline), true);
    assert.equal(validatePolygon([...outline].reverse()), true);
    assert.deepEqual(polygonBounds(outline), [.15, .15, .8, .7]);
    assert.equal(validatePolygon([[.1, .1], [.7, .8], [.8, .1], [.1, .7]]), false);
    assert.equal(validatePolygon([[.1, .1], [.7, .1], [.4, .1], [.4, .7], [.1, .7]]), false);
    assert.equal(validatePolygon([[.1, .1], [1.2, .1], [.5, .9]]), false);
});

test('lasso downsampling closes a large trace within the recipe limit', () => {
    const points = Array.from({length: 720}, (_, index) => {
        const a = index * Math.PI / 360;
        const radius = .25 + .028 * Math.sin(12 * a);
        return [.5 + Math.cos(a) * radius, .5 + Math.sin(a) * radius];
    });
    const outline = simplifyLasso([...points, points[0]], 48);
    assert.ok(outline.length <= 48);
    assert.ok(validatePolygon(outline));
    assert.notDeepEqual(outline[0], outline.at(-1));
    assert.ok(polygonBounds(outline)[0] < .26);
});
