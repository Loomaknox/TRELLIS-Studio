import {button, dialog, el, field, input, select} from './workbench-ui.js?v=3.4.0';
import {detailRefinements} from './hd-master-finishing.js?v=detail-refinement-native';

const number = value => Number.isFinite(value) ? value.toLocaleString('en-US') : '—';
const nameOf = job => job?.metadata?.display_name || job?.settings?.name || 'Source model';
const canCompare = job => job?.state === 'done' && job.media?.available !== false;
const labels = {queued: 'Queued', running: 'Finishing', done: 'Completed', error: 'Failed', cancelled: 'Cancelled'};
const defaults = [
    {label: 'High-detail copy', triangles: 1200000, bake_normals: false},
    {label: 'Game · 14K triangles', triangles: 14000, bake_normals: true},
    {label: 'Lightweight · 10K triangles', triangles: 10000, bake_normals: true},
];

export function createFinishingBoard({api, getRecords, refresh, compare}) {
    const ui = dialog('finishingBoard', 'Finishing board', 'CACHED SOURCE',
        'Queue finishing recipes on one saved source, then compare and keep a result.', 'finishing-board');
    const summary = el('p', 'finishing-summary');
    const selected = el('p', 'finishing-choice');
    const form = el('form', 'finishing-form');
    form.id = 'finishingBoardRecipes';
    const refinement = el('form', 'finishing-refinement');
    refinement.hidden = true;
    refinement.setAttribute('aria-labelledby', 'finishingBoardRefinement');
    const refinementHead = el('div', 'finishing-refinement-head');
    const refinementTitle = el('h3', '', 'Detail refinement');
    refinementTitle.id = 'finishingBoardRefinement';
    const credit = el('a', '', 'Powered by Hi3D 1.0');
    credit.href = 'http://hi3d.ai/';
    credit.target = '_blank';
    credit.rel = 'noopener noreferrer';
    refinementHead.append(refinementTitle, credit);
    const refinementHint = el('p', 'hint');
    const refinementGroup = el('fieldset', 'hd-master-options finishing-refinement-choices');
    refinementGroup.setAttribute('aria-label', 'Detail refinement resolution');
    const refinementChoices = Object.entries(detailRefinements).map(([value, method]) => {
        const control = input('radio', value, {name: 'detail_refinement'});
        const label = el('label', 'hd-master-method');
        const copy = el('span', 'hd-master-method-copy');
        const detail = el('small', '', method.detail);
        detail.id = `board-refinement-${value}`;
        control.setAttribute('aria-label', method.name);
        control.setAttribute('aria-describedby', detail.id);
        copy.append(el('strong', '', method.name), detail);
        label.append(control, copy);
        refinementGroup.append(label);
        return {method, control, detail};
    });
    const refinementTexture = select([], '');
    const refinementActions = el('div', 'finishing-refinement-actions');
    const refinementQueue = button('Queue refinement', 'layers', 'primary');
    refinementQueue.type = 'submit';
    refinementQueue.disabled = true;
    refinementActions.append(field('Texture size', refinementTexture), refinementQueue);
    refinement.append(refinementHead, refinementHint, refinementGroup, refinementActions);
    const results = el('section', 'finishing-results');
    const rows = el('div', 'finishing-rows');
    results.setAttribute('aria-labelledby', 'finishingBoardResults');
    const heading = el('h3', '', 'Source and variants');
    heading.id = 'finishingBoardResults';
    results.append(heading, selected, rows);
    ui.body.append(summary, refinement, form, results);
    const queue = button('Queue variants', 'layers', 'primary');
    queue.type = 'submit';
    queue.setAttribute('form', form.id);
    const footerHint = el('small', 'wb-footnote', 'Shared cache · Finishing uses the GPU');
    ui.foot.append(footerHint, queue);

    let base = null, board = null, drafts = [], opening = 0, pending = false;
    const cards = new Map();
    const request = (method, value) => api(`/api/jobs/${base.id}/finishing-board`, {
        method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(value),
    });

    function family() {
        if (!board) return [];
        const jobs = getRecords();
        const source = jobs.find(job => job.id === board.source_id);
        const variants = jobs.filter(job => job.settings?.source_kind === 'refinish'
            && job.settings.finish_source_id === board.source_id);
        variants.sort((left, right) => (right.settings.created || 0) - (left.settings.created || 0));
        return source ? [source, ...variants] : variants;
    }

    function updateQueueButton() {
        const count = drafts.filter(draft => draft.enabled.checked).length;
        queue.disabled = pending || !board || !count;
        queue.lastChild.textContent = count ? `Queue ${count} variant${count === 1 ? '' : 's'}` : 'Queue variants';
        const availableRefinement = !refinement.hidden && refinementChoices.some(({control}) => !control.disabled);
        refinementGroup.disabled = pending;
        refinementTexture.disabled = pending || !availableRefinement;
        const chosenRefinement = refinementChoices.some(({control}) => control.checked && !control.disabled);
        refinementQueue.disabled = pending || !board || !availableRefinement || !chosenRefinement || !refinementTexture.value;
    }

    function configureRefinement() {
        const config = board.master_finishing;
        const support = config?.methods || {};
        refinement.hidden = !refinementChoices.some(({control}) => support[control.value]);
        if (refinement.hidden) return;
        const textureSizes = board.texture_sizes.filter(size => [1024, 2048, 4096].includes(size));
        refinementTexture.replaceChildren(...textureSizes.map(size => new Option(`${size / 1024}K`, size)));
        const textureDefault = [base.settings.texture_size, config.default_texture_size, textureSizes[0]]
            .find(size => textureSizes.includes(size));
        refinementTexture.value = String(textureDefault || '');
        for (const {method, control, detail} of refinementChoices) {
            const capability = support[control.value];
            control.disabled = capability?.available !== true;
            control.checked = false;
            detail.textContent = control.disabled ? (capability?.reason || 'Unavailable for this source.') : method.detail;
        }
        const first = refinementChoices.find(({control}) => !control.disabled);
        if (first) first.control.checked = true;
        credit.hidden = !first;
        const source = Number.isFinite(config.source_resolution) ? ` · ${config.source_resolution}³ native source` : '';
        refinementHint.textContent = first
            ? `TRELLIS.2 single image${source} · Saved cutout`
            : 'Requires a native TRELLIS.2 single-image source at 512³, 1024³ or 1536³ with a saved cutout.';
        refinementActions.hidden = !first;
    }

    function recipeForm() {
        form.replaceChildren(el('h3', '', 'New recipes'));
        const textureChoices = board.texture_sizes.map(size => [size, `${size / 1024}K`]);
        const textureDefault = board.texture_sizes.includes(base.settings.texture_size) ? base.settings.texture_size : 2048;
        drafts = defaults.map(recipe => {
            const draft = el('fieldset', 'finishing-recipe');
            draft.append(el('legend', '', recipe.label));
            const enabled = input('checkbox', '');
            enabled.checked = true;
            const triangles = input('number', recipe.triangles, {min: 1000, max: 8000000, step: 1, required: ''});
            const texture = select(textureChoices, textureDefault);
            const modes = [['remesh', 'Remesh and simplify'], ['direct', 'Direct simplification']];
            if (board.repair_surface) modes.unshift(['repair', 'Surface reconstruction']);
            if (board.hd_reconstruction) modes.push(['hd', 'HD Reconstruction (768)']);
            if (board.wtivo_reconstruction) modes.push(['wtivo', 'WTiVo Reconstruction (1024)']);
            const mode = select(modes, board.repair_surface ? 'repair' : 'remesh');
            const repair = input('checkbox', '');
            repair.checked = false;
            const normals = input('checkbox', '');
            normals.checked = Boolean(recipe.bake_normals && board.normal_bake);
            const donorChoices = [['decoded', 'Original decoded surface']];
            if (board.normal_sources?.includes('parent')) donorChoices.push(['parent', 'Selected model · finished HD']);
            const donor = select(donorChoices, 'decoded');
            const donorField = field('Normal map detail source', donor);
            const resolutions = board.remesh_resolutions || [512];
            const grid = select(resolutions.map(size => [size, String(size)]), resolutions.includes(1024) ? 1024 : 512);
            const sampling = select((board.texture_sampling_modes || ['trilinear']).map(value =>
                [value, value === 'nearest' ? 'Nearest voxel · experimental' : 'Interpolated voxels']), 'trilinear');
            const gridField = field('Reconstruction resolution', grid);
            const repairField = field('Fill small holes', repair);
            const samplingField = field('Texture voxel sampling', sampling);
            const toggle = () => {
                const wtivo = mode.value === 'wtivo';
                const usesGrid = !['direct', 'hd', 'wtivo'].includes(mode.value);
                for (const control of [triangles, texture, mode]) control.disabled = !enabled.checked;
                normals.disabled = !enabled.checked || !board.normal_bake;
                donor.disabled = !enabled.checked || !normals.checked || !board.normal_bake;
                donorField.hidden = !normals.checked;
                repair.disabled = !enabled.checked || wtivo || mode.value === 'repair' || mode.value === 'hd';
                repairField.hidden = wtivo;
                sampling.disabled = !enabled.checked || wtivo;
                samplingField.hidden = wtivo;
                grid.disabled = !enabled.checked || !usesGrid;
                gridField.hidden = !usesGrid;
                updateQueueButton();
            };
            enabled.addEventListener('change', toggle);
            mode.addEventListener('change', () => {
                if (mode.value === 'hd') triangles.value = 1200000;
                toggle();
            });
            normals.addEventListener('change', toggle);
            draft.append(field('Include recipe', enabled), field('Target triangles', triangles),
                field('Texture size', texture), field('Finishing method', mode), gridField,
                repairField, field('Transfer surface detail to a normal map', normals), donorField, samplingField);
            form.append(draft);
            toggle();
            return {enabled, triangles, texture, mode, repair, normals, donor, grid, sampling};
        });
        form.append(el('p', 'hint', 'The saved master stays intact. Each recipe creates a separate copy using the original geometry and materials. A normal map carries surface relief, but cannot restore a lost silhouette or finger spacing.'));
        form.append(el('p', 'hint', 'These are comparison recipes, not validated game assets. Surface reconstruction includes hole repair and may close intended openings or soften detail. Higher reconstruction resolution uses more GPU memory. Nearest-voxel sampling can reveal blocks; it does not generate new texture detail.'));
        if (!board.normal_sources?.includes('parent')) form.append(el('p', 'hint', 'To bake from a finished HD model, first create and open a new high-detail copy. Older exports lack the alignment information required for this transfer.'));
        if (!board.normal_bake) form.append(el('p', 'hint', 'Install Blender to enable normal-map baking.'));
    }

    function rowFor(id) {
        if (cards.has(id)) return cards.get(id);
        const root = el('article', 'finishing-row');
        const title = el('strong');
        const metrics = el('p');
        const stage = el('small');
        const progress = el('progress');
        progress.max = 100;
        const text = el('div');
        text.append(title, metrics, stage, progress);
        const actions = el('div', 'finishing-row-actions');
        const compareButton = button('Compare', 'compare', 'secondary', () => {
            const jobs = family().filter(canCompare);
            const picked = jobs.find(job => job.id === id);
            const baseline = jobs.find(job => job.id === board.source_id && job.id !== id)
                || jobs.find(job => job.id !== id);
            if (!picked || !baseline) return;
            ui.close();
            compare.open(baseline, picked, {candidates: jobs, backToBoard: () => { ui.show(); update(); }});
        });
        const keep = button('Keep', 'check', 'secondary', () => choose(id));
        actions.append(compareButton, keep);
        root.append(text, actions);
        rows.append(root);
        const card = {root, title, metrics, stage, progress, compareButton, keep};
        cards.set(id, card);
        return card;
    }

    function update() {
        if (!ui.element.open) return;
        updateQueueButton();
        if (!board) return;
        const jobs = family();
        const retained = jobs.find(job => job.id === board.selected_id);
        selected.textContent = retained ? 'Kept for this board · ' + nameOf(retained)
            : board.selected_id ? 'The kept model is unavailable. Restore it or choose another result.'
                : 'Choose the variant to keep after reviewing its shape and materials.';
        const ids = new Set(jobs.map(job => job.id));
        for (const [id, card] of cards) {
            if (!ids.has(id)) {
                card.root.remove();
                cards.delete(id);
            }
        }
        const baseline = jobs.find(job => job.id === board.source_id);
        const baselineTriangles = baseline?.result?.triangles;
        const canPair = jobs.filter(canCompare).length >= 2;
        for (const [index, job] of jobs.entries()) {
            const card = rowFor(job.id);
            if (rows.children[index] !== card.root) rows.insertBefore(card.root, rows.children[index] || null);
            const isSource = job.id === board.source_id;
            const isKept = job.id === board.selected_id;
            const result = job.result || {};
            const method = isSource ? 'Original' : detailRefinements[job.settings?.master_finishing]?.name
                || (job.settings?.wtivo_reconstruction ? 'WTiVo 1024'
                    : job.generation_options?.mesh_mode === 'direct' ? 'Direct' : 'Remesh');
            const pieces = [method];
            pieces.push(Number.isFinite(result.triangles) ? `${number(result.triangles)} triangles`
                : `${number(job.settings.triangles)} target triangles`);
            const texture = result.texture_size ?? job.settings.texture_size;
            if (texture) pieces.push(`${texture / 1024}K textures`);
            if (!isSource && baselineTriangles && result.triangles) {
                const difference = (result.triangles / baselineTriangles - 1) * 100;
                pieces.push(`${difference > 0 ? '+' : ''}${difference.toFixed(1)}% vs original`);
            }
            if (Number.isFinite(result.seconds)) pieces.push(`${result.seconds} s`);
            if (Number.isFinite(result.peak_vram_gib)) pieces.push(`${result.peak_vram_gib} GiB peak VRAM`);
            if (result.neural_inferences === 0) pieces.push('0 inferences');
            card.title.textContent = nameOf(job);
            card.metrics.textContent = pieces.join(' · ');
            card.stage.textContent = [labels[job.state] || job.state,
                job.error || (job.state === 'done' ? '' : job.stage)].filter(Boolean).join(' · ');
            card.stage.classList.toggle('finishing-failure', job.state === 'error');
            card.progress.hidden = !['queued', 'running'].includes(job.state);
            card.progress.value = job.progress || 0;
            card.progress.setAttribute('aria-label', 'Progress for ' + nameOf(job));
            card.compareButton.disabled = !canPair || !canCompare(job);
            card.keep.disabled = pending || !canCompare(job);
            card.keep.lastChild.textContent = isKept ? 'Clear choice' : 'Keep';
            card.root.classList.toggle('finishing-kept', isKept);
        }
    }

    async function choose(id) {
        if (pending || !board) return;
        const token = opening;
        pending = true;
        ui.notice.textContent = '';
        update();
        try {
            const response = await request('PATCH', {selected_id: board.selected_id === id ? null : id});
            if (token === opening) board.selected_id = response.selected_id;
        } catch (error) {
            if (token === opening) ui.notice.textContent = error.message;
        } finally {
            if (token === opening) {
                pending = false;
                update();
            }
        }
    }

    refinement.onchange = updateQueueButton;
    refinement.onsubmit = async event => {
        event.preventDefault();
        if (refinementQueue.disabled) return;
        const choice = refinementChoices.find(({control}) => control.checked && !control.disabled);
        if (!choice) return;
        const token = opening;
        pending = true;
        ui.notice.textContent = 'Queueing detail refinement…';
        update();
        try {
            const response = await api(`/api/jobs/${base.id}/refinish`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    master_finishing: choice.control.value,
                    texture_size: Number(refinementTexture.value),
                }),
            });
            if (token === opening) {
                ui.notice.textContent = response.paused ? 'Refinement queued. Resume processing in Queue.'
                    : 'Refinement queued. Progress and results will appear here.';
            }
            await refresh();
        } catch (error) {
            if (token === opening) ui.notice.textContent = error.message;
        } finally {
            if (token === opening) {
                pending = false;
                update();
            }
        }
    };

    form.onsubmit = async event => {
        event.preventDefault();
        if (!board || pending || !form.reportValidity()) return;
        const variants = drafts.filter(draft => draft.enabled.checked).map(draft => {
            const shared = {
                triangles: draft.triangles.valueAsNumber,
                texture_size: Number(draft.texture.value),
                bake_normals: draft.normals.checked,
                normal_source: draft.normals.checked ? draft.donor.value : 'decoded',
            };
            if (draft.mode.value === 'wtivo') return {...shared, wtivo_reconstruction: true};
            return {
                ...shared,
                mesh_mode: draft.mode.value === 'direct' ? 'direct' : 'remesh',
                repair_surface: draft.mode.value === 'repair',
                ...(draft.mode.value === 'hd' ? {hd_reconstruction: true} : {}),
                repair_holes: draft.repair.checked,
                pre_simplify: false,
                remesh_resolution: Number(draft.grid.value),
                texture_sampling: draft.sampling.value,
            };
        });
        if (!variants.length) return;
        const token = opening;
        pending = true;
        ui.notice.textContent = 'Queuing variants…';
        update();
        try {
            const response = await request('POST', {variants});
            if (token === opening) {
                ui.notice.textContent = response.paused ? 'Variants queued. Resume processing in Queue.'
                    : 'Variants queued. Progress and results will appear here.';
            }
            await refresh();
        } catch (error) {
            if (token === opening) ui.notice.textContent = error.message;
        } finally {
            if (token === opening) {
                pending = false;
                update();
            }
        }
    };

    return {
        async open(job) {
            if (!job?.can_refinish) return;
            const token = ++opening;
            base = job;
            board = null;
            pending = false;
            drafts = [];
            cards.clear();
            rows.replaceChildren();
            form.replaceChildren();
            refinement.hidden = true;
            results.hidden = true;
            summary.textContent = nameOf(job);
            ui.show();
            ui.notice.textContent = 'Loading the saved finishing source…';
            update();
            try {
                const response = await api(`/api/jobs/${job.id}/finishing-board`);
                if (token !== opening) return;
                board = response;
                const source = getRecords().find(model => model.id === board.source_id);
                const size = board.cache_bytes / 1024 ** 2;
                summary.textContent = `${nameOf(source || job)} · ${size.toFixed(1)} MiB shared cache`;
                configureRefinement();
                recipeForm();
                results.hidden = false;
                ui.notice.textContent = '';
                update();
            } catch (error) {
                if (token === opening) ui.notice.textContent = error.message;
            }
        },
        update,
    };
}
