import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import {
    fitLinkedAffine,
    mapPoint,
    polygonBounds,
    validatePolygon,
    simplifyLasso,
} from './texture-projection-geometry.js?v=3.5.0';
import { button, dialog, el, field, input, select } from './workbench-ui.js?v=3.4.0';

const guides = ['Image-left eye', 'Image-right eye', 'Nose', 'Mouth'];
const clamp = (value) => Math.max(0, Math.min(1, value));
const nameOf = (job) => job?.metadata?.display_name || job?.settings?.name || 'Selected model';
const validRect = (rect) =>
    rect.every(Number.isFinite) && rect[2] - rect[0] > 0.002 && rect[3] - rect[1] > 0.002;
const pointsReady = (points) =>
    points.length === 4 &&
    [0, 1, 2, 3].every((index) => points[index]?.length === 2 && points[index].every(Number.isFinite));

function disposeModel(root) {
    const geometries = new Set(),
        materials = new Set(),
        textures = new Set();
    root?.traverse((object) => {
        if (object.geometry) geometries.add(object.geometry);
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
            if (!material) continue;
            materials.add(material);
            for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
        }
    });
    for (const texture of textures) {
        texture.dispose();
        texture.image?.close?.();
    }
    for (const material of materials) material.dispose();
    for (const geometry of geometries) geometry.dispose();
}

function loadImage(url) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () =>
            reject(new Error('This reference image could not be opened. Choose another image.'));
        image.src = url;
    });
}

async function frontImage(url, isCurrent) {
    let gltf, renderer;
    try {
        gltf = await new GLTFLoader().loadAsync(url);
        if (!isCurrent()) return null;
        let skinned = false;
        gltf.scene.traverse((object) => {
            if (object.isSkinnedMesh) skinned = true;
        });
        if (skinned) throw new Error('Texture projection currently requires a static model.');
        gltf.scene.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(gltf.scene, true);
        if (box.isEmpty()) throw new Error('The model has no visible surface to project onto.');
        const size = box.getSize(new THREE.Vector3()),
            center = box.getCenter(new THREE.Vector3());
        const side = Math.max(size.x, size.y, 0.001) * 1.08;
        const frame = [center.x - side / 2, center.y - side / 2, center.x + side / 2, center.y + side / 2];
        const camera = new THREE.OrthographicCamera(
            -side / 2,
            side / 2,
            side / 2,
            -side / 2,
            side / 10000,
            side * 10 + size.z * 4,
        );
        camera.position.set(center.x, center.y, box.max.z + side * 2 + size.z);
        camera.lookAt(center);
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x202724);
        scene.add(gltf.scene, new THREE.HemisphereLight(0xffffff, 0x566251, 2.8));
        const light = new THREE.DirectionalLight(0xffffff, 2.3);
        light.position.copy(center).add(new THREE.Vector3(side, side * 1.5, side * 2));
        light.target.position.copy(center);
        scene.add(light, light.target);
        renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
        renderer.setSize(1024, 1024, false);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.render(scene, camera);
        const image = await loadImage(renderer.domElement.toDataURL('image/png'));
        const bounds = [
            (box.min.x - frame[0]) / side,
            (frame[3] - box.max.y) / side,
            (box.max.x - frame[0]) / side,
            (frame[3] - box.min.y) / side,
        ];
        return isCurrent() ? { image, frame, bounds } : null;
    } finally {
        disposeModel(gltf?.scene);
        renderer?.dispose();
        renderer?.forceContextLoss();
        renderer?.domElement.remove();
    }
}

export function createTextureProjection({ api, startJob }) {
    const ui = dialog(
        'textureProjection',
        'Texture Projection',
        'REFERENCE TO SURFACE',
        'Select an area once on the image. Its outline and texture follow the same placement on the model.',
        'texture-projection-dialog',
    );
    const summary = el('p', 'hint');
    const reference = select([['', 'Choose a reference']], '');
    reference.id = 'projectionReference';
    const upload = input('file', '', { accept: 'image/png,image/jpeg,image/webp' });
    upload.id = 'projectionUpload';
    upload.hidden = true;
    const uploadButton = button('Choose image', 'image', 'secondary', () => upload.click());
    const uploadName = el('small', 'tp-upload-name', 'No image selected');
    const uploadControls = el('div', 'tp-upload-control');
    uploadControls.append(upload, uploadButton, uploadName);
    const referenceFields = el('div', 'tp-reference-fields');
    referenceFields.append(
        field('Saved reference', reference),
        field('Or upload an image', uploadControls, 'PNG, JPEG or WebP · up to 25 MB.'),
    );
    const mode = select(
        [
            ['selection', 'Select area'],
            ['placement', 'Move placement'],
            ['guides', 'Match face guides'],
            ['pan', 'Pan views'],
        ],
        'selection',
    );
    mode.id = 'projectionTool';
    const shape = select(
        [
            ['ellipse', 'Ellipse'],
            ['rectangle', 'Rectangle'],
            ['lasso', 'Lasso · freehand'],
            ['polygon', 'Polygon · point by point'],
        ],
        'ellipse',
    );
    shape.id = 'projectionMask';
    const undoButton = button('Undo', 'back', 'secondary', undo);
    undoButton.id = 'projectionUndo';
    const resetSelection = button('Reset selection', 'rotate', 'secondary', () => {
        remember();
        sourceRect = [...contentBounds];
        sourcePolygon = null;
        draft = [];
        shape.value = 'ellipse';
        changed();
    });
    const toolbar = el('div', 'tp-toolbar');
    toolbar.append(field('Tool', mode), field('Selection shape', shape), undoButton, resetSelection);
    const instruction = el('p', 'tp-instruction');
    instruction.setAttribute('role', 'status');
    const columns = el('div', 'tp-columns'),
        sides = {};
    for (const [key, title] of [
        ['source', '1 · Reference image'],
        ['target', '2 · Model front view'],
    ]) {
        const card = el('section', 'tp-card'),
            viewport = el('div', 'tp-viewport'),
            canvas = el('canvas', 'tp-canvas');
        canvas.width = canvas.height = 1024;
        canvas.tabIndex = 0;
        canvas.id = `projection${key === 'source' ? 'Source' : 'Target'}Canvas`;
        canvas.setAttribute(
            'aria-label',
            key === 'source'
                ? 'Reference image. Draw a selection or place a face guide.'
                : 'Model front view. Drag the linked placement or place a matching face guide.',
        );
        viewport.append(canvas);
        const zoom = input('range', 1, { min: 1, max: 6, step: 0.25 });
        zoom.id = `projection${key === 'source' ? 'Source' : 'Target'}Zoom`;
        const zoomValue = el('span', 'tp-zoom-value', '100%'),
            panButton = button('Pan', 'compass', 'secondary');
        panButton.setAttribute('aria-pressed', 'false');
        const fitButton = button('Fit', 'fit', 'secondary', () => {
            zoom.value = 1;
            applyZoom(key);
            viewport.scrollLeft = viewport.scrollTop = 0;
        });
        const controls = el('div', 'tp-view-controls');
        controls.append(field('Zoom', zoom), zoomValue, panButton, fitButton);
        const notice = el('p', 'hint');
        card.append(el('h3', '', title), controls, viewport, notice);
        columns.append(card);
        sides[key] = {
            image: null,
            points: [],
            canvas,
            viewport,
            zoom,
            zoomValue,
            panButton,
            notice,
            error: '',
            panMode: false,
        };
        zoom.oninput = () => applyZoom(key);
        panButton.onclick = () => {
            sides[key].panMode = !sides[key].panMode;
            changed();
        };
        canvas.onpointerdown = (event) => pointerDown(key, event);
        canvas.onpointermove = (event) => pointerMove(key, event);
        canvas.onpointerup = (event) => pointerUp(key, event);
        canvas.onpointercancel = () => cancelGesture();
        canvas.ondblclick = (event) => {
            if (key === 'source' && mode.value === 'selection' && shape.value === 'polygon') {
                event.preventDefault();
                closePolygon();
            }
        };
        canvas.onkeydown = (event) => {
            if (event.key === 'Enter' && key === 'source') {
                event.preventDefault();
                closePolygon();
            }
            if (event.key === 'Escape' && draft.length) {
                event.preventDefault();
                event.stopPropagation();
                draft = [];
                changed();
            }
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
                event.preventDefault();
                undo();
            }
        };
    }
    const closePolygonButton = button('Close polygon', 'check', 'secondary', () => closePolygon());
    closePolygonButton.id = 'projectionClosePolygon';
    const undoPointButton = button('Undo point', 'back', 'secondary', () => {
        draft.pop();
        changed();
    });
    undoPointButton.id = 'projectionUndoPoint';
    const polygonControls = el('div', 'tp-polygon-controls');
    polygonControls.append(
        closePolygonButton,
        undoPointButton,
        el('span', 'hint', 'Click points around the edge, then close the polygon. Enter also closes it.'),
    );
    const placementPanel = el('div', 'tp-placement');
    const placementScale = input('range', 1, { min: 0.25, max: 3, step: 0.01 });
    placementScale.id = 'projectionPlacementScale';
    const placementScaleValue = el('span', 'tp-zoom-value', '100%');
    const nudge = el('div', 'tp-nudges');
    for (const [label, x, y] of [
        ['Left', -0.005, 0],
        ['Up', 0, -0.005],
        ['Down', 0, 0.005],
        ['Right', 0.005, 0],
    ]) {
        const b = button(label, '', 'secondary', () => {
            remember();
            placement[2] += x;
            placement[5] += y;
            changed();
        });
        nudge.append(b);
    }
    const resetPlacement = button('Reset alignment', 'rotate', 'secondary', () => {
        remember();
        useGuides.checked = false;
        sides.source.points = [];
        sides.target.points = [];
        activePair = 0;
        initialisePlacement();
        mode.value = 'placement';
        changed();
    });
    placementPanel.append(
        field('Placement scale', placementScale),
        placementScaleValue,
        nudge,
        resetPlacement,
    );
    const useGuides = input('checkbox', '');
    useGuides.id = 'projectionAnchors';
    const guideToggle = el('label', 'check');
    guideToggle.append(useGuides, el('span', '', 'Use paired face guides for more precise alignment'));
    const guidePanel = el('section', 'tp-guides'),
        pairList = el('div', 'tp-pairs');
    const pairButtons = guides.map((label, index) => {
        const b = button(`${index + 1} · ${label}`, '', 'secondary', () => {
            activePair = index;
            mode.value = 'guides';
            changed();
        });
        pairList.append(b);
        return b;
    });
    const pairTitle = el('strong', 'tp-active-pair');
    const pairCoordinates = el('div', 'tp-pair-coordinates'),
        pointInputs = {};
    for (const key of ['source', 'target'])
        for (const axis of [0, 1]) {
            const control = input('number', '', { min: 0, max: 100, step: 0.1 });
            control.id = `projection${key}${axis}Guide`;
            pointInputs[`${key}${axis}`] = control;
            control.onchange = () => {
                const x = pointInputs[`${key}0`].value,
                    y = pointInputs[`${key}1`].value;
                if (x === '' || y === '') return;
                remember();
                sides[key].points[activePair] = [clamp(Number(x) / 100), clamp(Number(y) / 100)];
                changed();
            };
            pairCoordinates.append(
                field(`${key === 'source' ? 'Image' : 'Model'} ${axis ? 'Y' : 'X'} %`, control),
            );
        }
    const clearPair = button('Clear this pair', 'close', 'secondary', () => {
        remember();
        sides.source.points[activePair] = null;
        sides.target.points[activePair] = null;
        changed();
    });
    const resetGuides = button('Reset all guides', 'rotate', 'secondary', () => {
        remember();
        sides.source.points = [];
        sides.target.points = [];
        activePair = 0;
        changed();
    });
    const pairActions = el('div', 'tp-pair-actions');
    pairActions.append(clearPair, resetGuides);
    const guideTop = el('div', 'tp-guide-top');
    guideTop.append(pairList, pairTitle);
    guidePanel.append(
        el(
            'p',
            'hint',
            'Place the same named feature in both views. Drag a numbered marker to correct it. Guides can be outside the selected texture area.',
        ),
        pairCoordinates,
        pairActions,
    );
    const overlay = input('checkbox', '');
    overlay.checked = true;
    overlay.id = 'projectionOverlay';
    const overlayLabel = el('label', 'check');
    overlayLabel.append(overlay, el('span', '', 'Show texture alignment overlay'));
    const opacity = input('range', 1, { min: 0.1, max: 1, step: 0.05 });
    opacity.id = 'projectionOpacity';
    const feather = input('range', 0.06, { min: 0, max: 0.25, step: 0.01 });
    feather.id = 'projectionFeather';
    const adjustments = el('div', 'tp-adjustments');
    adjustments.append(overlayLabel, field('Texture strength', opacity), field('Soft edge', feather));
    const cropDetails = el('details', 'tp-crop-details');
    cropDetails.append(el('summary', '', 'Selection coordinates'));
    const cropFields = el('div', 'tp-coordinates'),
        rectInputs = [];
    for (const [i, label] of ['Left %', 'Top %', 'Right %', 'Bottom %'].entries()) {
        const control = input('number', 0, { min: 0, max: 100, step: 0.1 });
        rectInputs.push(control);
        control.onchange = () => {
            remember();
            sourceRect[i] = clamp(Number(control.value) / 100);
            sourcePolygon = null;
            if (['polygon', 'lasso'].includes(shape.value)) shape.value = 'rectangle';
            changed();
        };
        cropFields.append(field(label, control));
    }
    cropDetails.append(cropFields);
    const alignmentStatus = el('p', 'tp-alignment-status');
    alignmentStatus.setAttribute('role', 'status');
    ui.body.append(
        summary,
        referenceFields,
        toolbar,
        instruction,
        guideTop,
        columns,
        polygonControls,
        placementPanel,
        guideToggle,
        guidePanel,
        cropDetails,
        adjustments,
        alignmentStatus,
        el(
            'p',
            'hint',
            'The overlay is an alignment guide. The copy receives color on visible front-facing surfaces; geometry and the original model stay unchanged.',
        ),
    );
    const submit = button('Create texture copy', 'image', 'primary');
    submit.id = 'confirmTextureProjection';
    ui.foot.append(
        button('Cancel', 'close', 'secondary', () => ui.close()),
        submit,
    );

    let base = null,
        board = null,
        frame = null,
        targetBounds = [0, 0, 1, 1],
        contentBounds = [0, 0, 1, 1];
    let sourceRect = [0, 0, 1, 1],
        sourcePolygon = null,
        placement = [1, 0, 0, 0, 1, 0],
        initialPlacement = [...placement];
    let selectedReference = null,
        opening = 0,
        imageVersion = 0,
        uploadUrl = null,
        pending = false,
        uploading = false;
    let activePair = 0,
        draft = [],
        hover = null,
        gesture = null,
        history = [],
        scaleStart = null;
    let previousShape = shape.value,
        previousUseGuides = false;
    const snapshot = () => ({
        sourceRect: [...sourceRect],
        sourcePolygon: sourcePolygon?.map((p) => [...p]),
        placement: [...placement],
        sourcePoints: sides.source.points.map((p) => p && [...p]),
        targetPoints: sides.target.points.map((p) => p && [...p]),
        shape: shape.value,
        useGuides: useGuides.checked,
        activePair,
    });
    function remember() {
        history.push(snapshot());
        if (history.length > 40) history.shift();
    }
    function undo() {
        if (draft.length) {
            draft.pop();
            changed();
            return;
        }
        const previous = history.pop();
        if (!previous || pending) return;
        ({ sourceRect, sourcePolygon, placement, activePair } = previous);
        sides.source.points = previous.sourcePoints;
        sides.target.points = previous.targetPoints;
        shape.value = previous.shape;
        useGuides.checked = previous.useGuides;
        changed();
    }
    function selectionOutline() {
        if (sourcePolygon?.length) return sourcePolygon;
        const [x0, y0, x1, y1] = sourceRect;
        if (shape.value !== 'ellipse')
            return [
                [x0, y0],
                [x1, y0],
                [x1, y1],
                [x0, y1],
            ];
        return Array.from({ length: 72 }, (_, i) => {
            const a = (i * Math.PI) / 36;
            return [
                (x0 + x1) / 2 + ((x1 - x0) / 2) * Math.cos(a),
                (y0 + y1) / 2 + ((y1 - y0) / 2) * Math.sin(a),
            ];
        });
    }
    function activeTransform() {
        return useGuides.checked
            ? pointsReady(sides.source.points) && pointsReady(sides.target.points)
                ? fitLinkedAffine(sides.source.points, sides.target.points)
                : null
            : placement;
    }
    function targetRect(transform) {
        return polygonBounds(selectionOutline().map((point) => mapPoint(transform, point)));
    }
    function initialisePlacement() {
        if (!sides.source.image || !sides.target.image) return;
        const b = contentBounds,
            t = targetBounds,
            aspect = sides.source.image.naturalWidth / sides.source.image.naturalHeight;
        const scale = Math.min((t[2] - t[0]) / ((b[2] - b[0]) * aspect), (t[3] - t[1]) / (b[3] - b[1]));
        placement = [
            scale * aspect,
            0,
            (t[0] + t[2]) / 2 - (scale * aspect * (b[0] + b[2])) / 2,
            0,
            scale,
            (t[1] + t[3]) / 2 - (scale * (b[1] + b[3])) / 2,
        ];
        initialPlacement = [...placement];
        placementScale.value = 1;
    }
    function alphaBounds(image) {
        const canvas = document.createElement('canvas'),
            scale = Math.min(1, 1024 / Math.max(image.naturalWidth, image.naturalHeight));
        canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        try {
            const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            let x0 = canvas.width,
                y0 = canvas.height,
                x1 = 0,
                y1 = 0,
                transparent = false;
            for (let y = 0; y < canvas.height; y++)
                for (let x = 0; x < canvas.width; x++) {
                    const alpha = pixels[(y * canvas.width + x) * 4 + 3];
                    if (alpha < 250) transparent = true;
                    if (alpha > 16) {
                        x0 = Math.min(x0, x);
                        y0 = Math.min(y0, y);
                        x1 = Math.max(x1, x + 1);
                        y1 = Math.max(y1, y + 1);
                    }
                }
            return transparent && x1 > x0 && y1 > y0
                ? [x0 / canvas.width, y0 / canvas.height, x1 / canvas.width, y1 / canvas.height]
                : [0, 0, 1, 1];
        } catch {
            return [0, 0, 1, 1];
        } finally {
            canvas.width = canvas.height = 1;
        }
    }
    function path(ctx, points, w, h, close = true) {
        ctx.beginPath();
        if (!points.length) return;
        ctx.moveTo(points[0][0] * w, points[0][1] * h);
        for (const p of points.slice(1)) ctx.lineTo(p[0] * w, p[1] * h);
        if (close) ctx.closePath();
    }
    function draw(key) {
        const side = sides[key],
            canvas = side.canvas,
            ctx = canvas.getContext('2d'),
            w = canvas.width,
            h = canvas.height;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = '#171e1a';
        ctx.fillRect(0, 0, w, h);
        if (!side.image) return;
        ctx.drawImage(side.image, 0, 0, w, h);
        const transform = activeTransform(),
            outline = selectionOutline(),
            shown = key === 'source' ? outline : transform ? outline.map((p) => mapPoint(transform, p)) : [];
        if (key === 'target' && transform && overlay.checked && sides.source.image && validRect(sourceRect)) {
            ctx.save();
            path(ctx, shown, w, h);
            ctx.clip();
            ctx.globalAlpha = 0.55 * Number(opacity.value);
            ctx.setTransform(
                transform[0] * w,
                transform[3] * h,
                transform[1] * w,
                transform[4] * h,
                transform[2] * w,
                transform[5] * h,
            );
            ctx.drawImage(sides.source.image, 0, 0, 1, 1);
            ctx.restore();
        }
        const ratio = w / (canvas.clientWidth || w);
        ctx.lineWidth = 2 * ratio;
        ctx.strokeStyle = '#d5ff98';
        ctx.setLineDash([7 * ratio, 4 * ratio]);
        path(ctx, shown, w, h);
        ctx.stroke();
        ctx.setLineDash([]);
        if (key === 'source' && draft.length) {
            ctx.strokeStyle = '#ffca81';
            path(ctx, [...draft, ...(hover && shape.value === 'polygon' ? [hover] : [])], w, h, false);
            ctx.stroke();
            for (const p of draft) {
                ctx.beginPath();
                ctx.arc(p[0] * w, p[1] * h, 3 * ratio, 0, Math.PI * 2);
                ctx.fillStyle = '#ffca81';
                ctx.fill();
            }
        }
        if (useGuides.checked)
            for (const [index, p] of side.points.entries())
                if (p) {
                    ctx.fillStyle = index === activePair ? '#ffca81' : '#c4f58a';
                    ctx.strokeStyle = '#172015';
                    ctx.lineWidth = 2 * ratio;
                    ctx.beginPath();
                    ctx.arc(p[0] * w, p[1] * h, 9 * ratio, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.stroke();
                    ctx.fillStyle = '#172015';
                    ctx.font = `bold ${11 * ratio}px sans-serif`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(String(index + 1), p[0] * w, p[1] * h);
                    ctx.font = `${11 * ratio}px sans-serif`;
                    const text = guides[index],
                        width = ctx.measureText(text).width;
                    const x = Math.max(2 * ratio, Math.min(w - width - 8 * ratio, p[0] * w + 13 * ratio));
                    const y = Math.max(8 * ratio, p[1] * h - 15 * ratio);
                    ctx.fillStyle = '#172015dd';
                    ctx.fillRect(x - 3 * ratio, y - 8 * ratio, width + 6 * ratio, 16 * ratio);
                    ctx.fillStyle = '#fff';
                    ctx.textAlign = 'left';
                    ctx.fillText(text, x, y);
                }
    }
    function changed() {
        const ready = !!(sides.source.image && sides.target.image),
            transform = ready ? activeTransform() : null;
        const polygonValid =
            !['polygon', 'lasso'].includes(shape.value) || (sourcePolygon && validatePolygon(sourcePolygon));
        const bounds = transform && targetRect(transform),
            fits =
                bounds &&
                bounds.every(Number.isFinite) &&
                bounds[0] >= -1e-8 &&
                bounds[1] >= -1e-8 &&
                bounds[2] <= 1 + 1e-8 &&
                bounds[3] <= 1 + 1e-8;
        submit.disabled =
            pending ||
            uploading ||
            !board?.supported ||
            !frame ||
            !selectedReference ||
            !ready ||
            !validRect(sourceRect) ||
            !polygonValid ||
            draft.length > 0 ||
            !transform ||
            !fits;
        reference.disabled = uploadButton.disabled = pending || uploading || !board?.supported;
        for (const key of ['source', 'target']) {
            const side = sides[key];
            side.panButton.setAttribute('aria-pressed', String(side.panMode));
            side.canvas.style.cursor =
                side.panMode || mode.value === 'pan'
                    ? 'grab'
                    : key === 'target' && !useGuides.checked
                      ? 'move'
                      : 'crosshair';
            side.canvas.style.touchAction = 'none';
            draw(key);
            side.notice.textContent =
                side.error ||
                (key === 'source'
                    ? 'Draw only here. The selection is linked to the model.'
                    : useGuides.checked
                      ? 'Placement follows the matching guide pairs.'
                      : 'Drag here to move the linked placement.');
        }
        polygonControls.hidden = !(mode.value === 'selection' && shape.value === 'polygon');
        closePolygonButton.disabled = draft.length < 3;
        undoPointButton.disabled = !draft.length;
        guidePanel.hidden = guideTop.hidden = !useGuides.checked;
        placementPanel.hidden = useGuides.checked;
        undoButton.disabled = pending || (!history.length && !draft.length);
        placementScale.disabled = useGuides.checked || !ready || pending;
        for (const b of nudge.children) b.disabled = placementScale.disabled;
        const relative = initialPlacement[0] ? placement[0] / initialPlacement[0] : 1;
        placementScale.value = relative;
        placementScaleValue.textContent = `${Math.round(relative * 100)}%`;
        rectInputs.forEach((control, i) => {
            if (document.activeElement !== control) control.value = (sourceRect[i] * 100).toFixed(1);
        });
        pairButtons.forEach((b, i) => {
            b.setAttribute('aria-pressed', String(i === activePair));
            b.textContent = `${i + 1} · ${guides[i]} · ${sides.source.points[i] ? 'Image ✓' : 'Image —'} / ${sides.target.points[i] ? 'Model ✓' : 'Model —'}`;
        });
        pairTitle.textContent = `Active pair: ${activePair + 1} · ${guides[activePair]}`;
        for (const key of ['source', 'target'])
            for (const axis of [0, 1]) {
                const control = pointInputs[`${key}${axis}`];
                if (document.activeElement !== control)
                    control.value = sides[key].points[activePair]
                        ? (sides[key].points[activePair][axis] * 100).toFixed(1)
                        : '';
            }
        instruction.textContent =
            mode.value === 'pan'
                ? 'Drag either view to pan. Each zoom is independent.'
                : mode.value === 'guides'
                  ? `Place ${guides[activePair].toLowerCase()} in the image and model. A completed pair advances to the next missing pair.`
                  : mode.value === 'placement'
                    ? 'Drag the outline on the model, use the arrow buttons, or adjust placement scale.'
                    : shape.value === 'lasso'
                      ? 'Draw freely around the texture area. Release to close the lasso.'
                      : shape.value === 'polygon'
                        ? 'Click around the texture area. Close the polygon, double-click, or press Enter when finished.'
                        : 'Drag around the texture area in the reference. You do not need to select it again on the model.';
        alignmentStatus.textContent = !ready
            ? ''
            : draft.length
              ? 'Finish the current outline before creating the copy.'
              : !polygonValid
                ? 'Draw a closed outline with at least three points and no crossing edges.'
                : !validRect(sourceRect)
                  ? 'Select an area with a non-zero width and height.'
                  : !transform
                    ? useGuides.checked &&
                      (!pointsReady(sides.source.points) || !pointsReady(sides.target.points))
                        ? 'Place all four matching pairs. The selection can be anywhere relative to the guides.'
                        : 'The guide pairs do not form a consistent alignment. Check the same named features in both views.'
                    : !fits
                      ? 'The linked selection extends beyond the model view. Move it inward, reduce its scale, or correct the guide pairs.'
                      : 'Selection and placement are linked. Review the outline on the model before creating the copy.';
        previousShape = shape.value;
        previousUseGuides = useGuides.checked;
    }
    function applyZoom(key) {
        const side = sides[key],
            oldWidth = side.canvas.clientWidth || side.viewport.clientWidth,
            oldHeight = side.canvas.clientHeight || side.viewport.clientHeight;
        const center = [
            (side.viewport.scrollLeft + side.viewport.clientWidth / 2) / oldWidth,
            (side.viewport.scrollTop + side.viewport.clientHeight / 2) / oldHeight,
        ];
        const aspect = side.image ? side.image.naturalWidth / side.image.naturalHeight : 1;
        side.canvas.style.width = `${Math.min(side.viewport.clientWidth, side.viewport.clientHeight * aspect) * Number(side.zoom.value)}px`;
        side.zoomValue.textContent = `${Math.round(Number(side.zoom.value) * 100)}%`;
        side.viewport.scrollLeft = center[0] * side.canvas.clientWidth - side.viewport.clientWidth / 2;
        side.viewport.scrollTop = center[1] * side.canvas.clientHeight - side.viewport.clientHeight / 2;
        draw(key);
    }
    const position = (key, event) => {
        const rect = sides[key].canvas.getBoundingClientRect();
        return [
            clamp((event.clientX - rect.left) / rect.width),
            clamp((event.clientY - rect.top) / rect.height),
        ];
    };
    function pointerDown(key, event) {
        if (pending || !sides[key].image || event.button !== 0) return;
        const side = sides[key],
            point = position(key, event);
        event.preventDefault();
        side.canvas.focus();
        if (side.panMode || mode.value === 'pan' || event.altKey) {
            gesture = {
                kind: 'pan',
                key,
                start: [event.clientX, event.clientY],
                scroll: [side.viewport.scrollLeft, side.viewport.scrollTop],
            };
        } else if (mode.value === 'guides') {
            useGuides.checked = true;
            const rect = side.canvas.getBoundingClientRect();
            let hit = -1,
                nearest = 15;
            if (side.points[activePair])
                side.points.forEach((p, index) => {
                    if (!p) return;
                    const distance = Math.hypot(
                        (p[0] - point[0]) * rect.width,
                        (p[1] - point[1]) * rect.height,
                    );
                    if (distance < nearest) {
                        hit = index;
                        nearest = distance;
                    }
                });
            if (hit >= 0) activePair = hit;
            remember();
            gesture = { kind: 'guide', key, index: activePair, newPoint: !side.points[activePair] };
            side.points[activePair] = point;
        } else if (key === 'target') {
            if (useGuides.checked) {
                ui.notice.textContent =
                    'Placement is controlled by the guide pairs. Edit a guide or turn off paired guides to move it freely.';
                return;
            }
            remember();
            gesture = { kind: 'placement', key, start: point, original: [...placement] };
        } else if (mode.value === 'selection') {
            if (shape.value === 'polygon') {
                if (!draft.length) remember();
                if (
                    draft.length >= 3 &&
                    Math.hypot(
                        (point[0] - draft[0][0]) * side.canvas.clientWidth,
                        (point[1] - draft[0][1]) * side.canvas.clientHeight,
                    ) < 12
                ) {
                    closePolygon();
                    return;
                }
                if (draft.length >= 128) {
                    ui.notice.textContent =
                        'A polygon can contain up to 128 points. Close it or undo a point.';
                    return;
                }
                if (
                    !draft.length ||
                    Math.hypot(point[0] - draft.at(-1)[0], point[1] - draft.at(-1)[1]) > 1e-5
                )
                    draft.push(point);
                changed();
                return;
            }
            remember();
            sourcePolygon = null;
            gesture = { kind: shape.value === 'lasso' ? 'lasso' : 'region', key, start: point };
            if (gesture.kind === 'lasso') draft = [point];
        } else return;
        side.canvas.setPointerCapture(event.pointerId);
        changed();
    }
    function pointerMove(key, event) {
        const point = position(key, event);
        hover = point;
        if (!gesture) {
            if (key === 'source' && draft.length) draw('source');
            return;
        }
        if (gesture.key !== key) return;
        const side = sides[key];
        if (gesture.kind === 'pan') {
            side.viewport.scrollLeft = gesture.scroll[0] + gesture.start[0] - event.clientX;
            side.viewport.scrollTop = gesture.scroll[1] + gesture.start[1] - event.clientY;
            return;
        }
        if (gesture.kind === 'guide') side.points[gesture.index] = point;
        if (gesture.kind === 'placement') {
            placement = [...gesture.original];
            placement[2] += point[0] - gesture.start[0];
            placement[5] += point[1] - gesture.start[1];
        }
        if (gesture.kind === 'region')
            sourceRect = [
                Math.min(point[0], gesture.start[0]),
                Math.min(point[1], gesture.start[1]),
                Math.max(point[0], gesture.start[0]),
                Math.max(point[1], gesture.start[1]),
            ];
        if (gesture.kind === 'lasso') {
            const last = draft.at(-1);
            if (
                Math.hypot(
                    (point[0] - last[0]) * side.canvas.clientWidth,
                    (point[1] - last[1]) * side.canvas.clientHeight,
                ) >= 2
            )
                draft.push(point);
        }
        changed();
    }
    function pointerUp(key, event) {
        if (!gesture || gesture.key !== key) return;
        const current = gesture;
        gesture = null;
        if (sides[key].canvas.hasPointerCapture(event.pointerId))
            sides[key].canvas.releasePointerCapture(event.pointerId);
        if (current.kind === 'lasso') closePolygon(true);
        if (
            current.kind === 'guide' &&
            current.newPoint &&
            sides.source.points[current.index] &&
            sides.target.points[current.index]
        ) {
            const next = [0, 1, 2, 3].find((i) => !sides.source.points[i] || !sides.target.points[i]);
            if (next !== undefined) activePair = next;
        }
        changed();
    }
    function cancelGesture() {
        if (gesture && gesture.kind !== 'pan') {
            gesture = null;
            draft = [];
            undo();
        }
        gesture = null;
        changed();
    }
    function closePolygon(fromLasso = false) {
        if (draft.length < 3) return;
        let points = fromLasso ? simplifyLasso(draft, 128) : draft;
        if (
            points.length > 1 &&
            Math.hypot(points[0][0] - points.at(-1)[0], points[0][1] - points.at(-1)[1]) < 1e-5
        )
            points = points.slice(0, -1);
        if (!validatePolygon(points)) {
            ui.notice.textContent =
                'This outline crosses itself or is too small. Undo the last point or draw it again.';
            if (fromLasso) {
                draft = [];
                sourcePolygon = null;
            }
            changed();
            return;
        }
        sourcePolygon = points.map((p) => [...p]);
        sourceRect = polygonBounds(sourcePolygon);
        draft = [];
        hover = null;
        ui.notice.textContent = '';
        changed();
    }
    mode.onchange = () => {
        draft = [];
        if (mode.value === 'guides') useGuides.checked = true;
        changed();
    };
    shape.onchange = () => {
        remember();
        history.at(-1).shape = previousShape;
        sourcePolygon = null;
        draft = [];
        mode.value = 'selection';
        changed();
    };
    useGuides.onchange = () => {
        remember();
        history.at(-1).useGuides = previousUseGuides;
        mode.value = useGuides.checked ? 'guides' : 'placement';
        changed();
    };
    placementScale.onpointerdown = () => {
        remember();
        scaleStart = [...placement];
    };
    placementScale.oninput = () => {
        if (useGuides.checked) return;
        if (!scaleStart) {
            remember();
            scaleStart = [...placement];
        }
        const center = mapPoint(scaleStart, [
            (sourceRect[0] + sourceRect[2]) / 2,
            (sourceRect[1] + sourceRect[3]) / 2,
        ]);
        const ratio = Number(placementScale.value),
            a = initialPlacement[0] * ratio,
            e = initialPlacement[4] * ratio;
        placement = [
            a,
            0,
            center[0] - (a * (sourceRect[0] + sourceRect[2])) / 2,
            0,
            e,
            center[1] - (e * (sourceRect[1] + sourceRect[3])) / 2,
        ];
        changed();
    };
    placementScale.onchange = () => {
        scaleStart = null;
    };
    overlay.onchange = opacity.oninput = feather.oninput = changed;
    async function chooseReference(descriptor, selection) {
        const version = ++imageVersion;
        sides.source.image = null;
        sides.source.error = '';
        selectedReference = null;
        changed();
        try {
            const image = await loadImage(descriptor.url);
            if (version !== imageVersion || !ui.element.open) return;
            sides.source.image = image;
            sides.source.canvas.height = Math.round((1024 * image.naturalHeight) / image.naturalWidth);
            contentBounds = alphaBounds(image);
            sourceRect = [...contentBounds];
            sourcePolygon = null;
            draft = [];
            history = [];
            activePair = 0;
            sides.source.points = [];
            sides.target.points = [];
            useGuides.checked = false;
            mode.value = 'selection';
            shape.value = 'ellipse';
            selectedReference = selection;
            initialisePlacement();
            sides.source.zoom.value = 1;
            applyZoom('source');
            if (frame) ui.notice.textContent = '';
            changed();
        } catch (error) {
            if (version === imageVersion && ui.element.open) {
                sides.source.error = error.message;
                changed();
            }
        }
    }
    reference.onchange = () => {
        const item = board?.references?.find((entry) => entry.id === reference.value);
        if (item) chooseReference(item, { reference: item.id });
        else {
            imageVersion++;
            selectedReference = null;
            sides.source.image = null;
            changed();
        }
    };
    upload.onchange = async () => {
        const file = upload.files?.[0];
        if (!file || uploading) return;
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
            ui.notice.textContent = 'Choose a PNG, JPEG or WebP image.';
            upload.value = '';
            return;
        }
        if (file.size > 25 * 1024 * 1024) {
            ui.notice.textContent = 'Choose an image no larger than 25 MB.';
            upload.value = '';
            return;
        }
        const version = opening;
        uploading = true;
        changed();
        ui.notice.textContent = 'Uploading reference image…';
        try {
            const data = new FormData();
            data.append('file', file);
            const result = await api('/api/v1/uploads', { method: 'POST', body: data });
            if (version !== opening || !ui.element.open) return;
            if (!result.id) throw Error('The upload did not return a reference ID.');
            if (uploadUrl) URL.revokeObjectURL(uploadUrl);
            uploadUrl = URL.createObjectURL(file);
            reference.value = '';
            uploadName.textContent = file.name;
            await chooseReference({ url: uploadUrl }, { upload_id: result.id });
        } catch (error) {
            if (version === opening && ui.element.open) ui.notice.textContent = error.message;
        } finally {
            if (version === opening) {
                uploading = false;
                changed();
            }
            upload.value = '';
        }
    };
    submit.onclick = async () => {
        if (submit.disabled || !base) return;
        const transform = activeTransform(),
            bounds = targetRect(transform),
            id = base.id,
            version = opening;
        const value = {
            ...selectedReference,
            linked_selection: true,
            camera: { view: 'front', frame: [...frame] },
            source_rect: [...sourceRect],
            target_rect: bounds.map(clamp),
            mask_shape: sourcePolygon ? 'polygon' : shape.value,
            opacity: Number(opacity.value),
            feather: Number(feather.value),
        };
        if (sourcePolygon) value.source_polygon = sourcePolygon.map((p) => [...p]);
        if (useGuides.checked) {
            value.source_points = sides.source.points.map((p) => [...p]);
            value.target_points = sides.target.points.map((p) => [...p]);
        }
        pending = true;
        changed();
        ui.notice.textContent = 'Queueing texture projection…';
        try {
            const result = await api(`/api/v1/models/${id}/texture-projection`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(value),
            });
            if (version === opening) ui.close();
            await startJob(result.id);
        } catch (error) {
            if (version === opening && ui.element.open) ui.notice.textContent = error.message;
        } finally {
            if (version === opening) {
                pending = false;
                changed();
            }
        }
    };
    ui.element.addEventListener('close', () => {
        if (ui.element.open) return;
        opening++;
        imageVersion++;
        base = board = frame = selectedReference = null;
        pending = uploading = false;
        gesture = null;
        draft = [];
        history = [];
        resizeObserver.disconnect();
        for (const side of Object.values(sides)) {
            side.image = null;
            side.points = [];
            side.canvas.width = side.canvas.height = 1;
        }
        if (uploadUrl) URL.revokeObjectURL(uploadUrl);
        uploadUrl = null;
        upload.value = '';
        uploadName.textContent = 'No image selected';
    });
    const resizeObserver = new ResizeObserver(() => {
        if (ui.element.open) {
            ui.element.style.setProperty('--tp-header-height', `${ui.element.querySelector('header').offsetHeight}px`);
            for (const key of ['source', 'target']) applyZoom(key);
        }
    });
    return {
        async open(job) {
            if (!job || job.state !== 'done' || ui.element.open) return;
            base = job;
            board = frame = selectedReference = null;
            pending = uploading = false;
            useGuides.checked = false;
            overlay.checked = true;
            shape.value = 'ellipse';
            mode.value = 'selection';
            opacity.value = 1;
            feather.value = 0.06;
            sourceRect = contentBounds = [0, 0, 1, 1];
            sourcePolygon = null;
            placement = [1, 0, 0, 0, 1, 0];
            initialPlacement = [...placement];
            draft = [];
            history = [];
            activePair = 0;
            for (const side of Object.values(sides)) {
                side.image = null;
                side.error = '';
                side.points = [];
                side.canvas.width = side.canvas.height = 1024;
                side.zoom.value = 1;
                side.canvas.style.width = '100%';
                side.panMode = false;
                side.viewport.scrollTop = side.viewport.scrollLeft = 0;
                side.zoomValue.textContent = '100%';
            }
            const version = ++opening;
            summary.textContent = nameOf(job);
            ui.show();
            for (const side of Object.values(sides)) resizeObserver.observe(side.viewport);
            resizeObserver.observe(ui.element.querySelector('header'));
            ui.notice.textContent = 'Checking this model…';
            changed();
            try {
                const response = await api(`/api/v1/models/${job.id}/texture-projection`);
                if (version !== opening || !ui.element.open) return;
                board = response;
                reference.replaceChildren(el('option', '', 'Choose a reference'));
                reference.firstChild.value = '';
                for (const item of board.references || []) {
                    const option = el('option', '', item.label);
                    option.value = item.id;
                    reference.append(option);
                }
                if (!board.supported) {
                    ui.notice.textContent =
                        board.reason || 'Texture projection is not available for this model.';
                    changed();
                    return;
                }
                if (board.linked_selection !== true) {
                    board.supported = false;
                    ui.notice.textContent =
                        'The server needs the matching Texture Projection update. Restart Studio and reload this page.';
                    changed();
                    return;
                }
                ui.notice.textContent = 'Preparing the model front view…';
                const ref = board.references?.[0];
                if (ref) {
                    reference.value = ref.id;
                    chooseReference(ref, { reference: ref.id });
                }
                const preview = await frontImage(
                    `/api/jobs/${job.id}/files/model.glb?v=${encodeURIComponent(job.result?.revision || job.id)}`,
                    () => version === opening && ui.element.open,
                );
                if (!preview) return;
                frame = preview.frame;
                targetBounds = preview.bounds;
                sides.target.image = preview.image;
                initialisePlacement();
                applyZoom('target');
                ui.notice.textContent = '';
                changed();
            } catch (error) {
                if (version === opening && ui.element.open) {
                    ui.notice.textContent = error.message;
                    changed();
                }
            }
        },
    };
}

export function createBakedGameCopy({api, startJob}) {
    const ui = dialog('bakedGameCopy', 'Game Copy from HD', 'DETAIL TRANSFER',
        'Create a lighter copy with new UVs and textures baked from the selected high-detail model.');
    const summary = el('p', 'hint'), profile = select([['object', 'Object · 28K triangles'], ['humanoid', 'Humanoid · 14K triangles']], 'object');
    const triangles = input('number', 28000, {min: 5000, max: 150000, step: 1, required: ''}); triangles.id = 'bakedGameTriangles';
    const texture = select([[1024, '1K'], [2048, '2K'], [4096, '4K']], 2048); texture.id = 'bakedGameTexture';
    const normals = input('checkbox', ''); normals.checked = true; normals.id = 'bakedGameNormals';
    const normalLabel = el('label', 'check'); normalLabel.append(normals, el('span', '', 'Transfer surface detail to a normal map'));
    const normalHint = el('p', 'hint');
    const form = el('form'); form.id = 'bakedGameForm';
    form.append(summary, field('Profile', profile), field('Target triangle count', triangles), field('Texture resolution', texture), normalLabel, normalHint, el('p', 'hint', 'Color and material maps are transferred from the HD model. Compare fine parts, faces and hands with the original after processing.'));
    const submit = button('Create game copy', 'cube', 'primary'); submit.type = 'submit'; submit.setAttribute('form', form.id); submit.id = 'confirmBakedGameCopy';
    ui.body.append(form); ui.foot.append(button('Cancel', 'close', 'secondary', () => ui.close()), submit);
    let base = null, supported = false, opening = 0, pending = false;
    profile.onchange = () => {
        triangles.value = profile.value === 'humanoid' ? 14000 : 28000;
        triangles.setCustomValidity('');
    };
    ui.element.addEventListener('close', () => { if (ui.element.open) return; opening++; base = null; supported = false; pending = false; });
    form.onsubmit = async event => {
        event.preventDefault(); if (!base || !supported || pending || !form.reportValidity()) return;
        const id = base.id, version = opening; pending = true; submit.disabled = true; ui.notice.textContent = 'Queueing game copy…';
        try {
            const result = await api(`/api/v1/models/${id}/baked-game-copy`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({triangles: Number(triangles.value), texture_size: Number(texture.value), profile: profile.value, bake_normals: normals.checked})});
            if (version === opening) ui.close(); await startJob(result.id);
        } catch (error) { if (version === opening && ui.element.open) ui.notice.textContent = error.message; }
        finally { if (version === opening) { pending = false; submit.disabled = !supported; } }
    };
    return {async open(job) {
        if (!job || job.state !== 'done') return;
        if (ui.element.open) return;
        base = job; supported = false; pending = false; const version = ++opening;
        normals.checked = true; normals.disabled = false; normalHint.textContent = '';
        triangles.setCustomValidity('');
        summary.textContent = nameOf(job); submit.disabled = true; ui.show(); ui.notice.textContent = 'Checking this model…';
        try {
            const response = await api(`/api/v1/models/${job.id}/baked-game-copy`);
            if (version !== opening || !ui.element.open) return;
            supported = response.supported === true && response.ready !== false;
            const available = response.profiles || ['object'];
            profile.replaceChildren(...available.filter(value => ['object', 'humanoid'].includes(value)).map(value => { const option = el('option', '', value === 'humanoid' ? 'Humanoid · 14K triangles' : 'Object · 28K triangles'); option.value = value; return option; }));
            profile.value = response.humanoid && available.includes('humanoid') ? 'humanoid' : 'object';
            if (!profile.value) profile.selectedIndex = 0;
            triangles.value = response.default_triangles || (profile.value === 'humanoid' ? 14000 : 28000);
            texture.replaceChildren(...(response.texture_sizes || [1024, 2048, 4096]).map(size => { const option = el('option', '', `${size / 1024}K`); option.value = size; return option; })); texture.value = 2048;
            if (!texture.value) texture.selectedIndex = 0;
            if (response.triangle_limits?.length === 2) { triangles.min = response.triangle_limits[0]; triangles.max = response.triangle_limits[1]; }
            normals.disabled = response.has_normal_map === true;
            normalHint.textContent = normals.disabled ? 'Normal-map transfer is required to preserve the source model’s existing surface detail.' : '';
            ui.notice.textContent = supported ? '' : response.reason || response.dependencies?.reason || (response.ready === false ? 'Game-copy tools are not ready. Install the required components and restart Studio.' : 'Game Copy from HD is not available for this model.'); submit.disabled = !supported;
        } catch (error) { if (version === opening && ui.element.open) ui.notice.textContent = error.message; }
    }};
}
