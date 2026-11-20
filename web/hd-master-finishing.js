import {formatLocale,t} from './i18n.js';
import {button, dialog, el, field, select} from './workbench-ui.js?v=3.4.0';

export const detailRefinements = {
    hi3d_512: {
        name: t('Detail Refinement (512)'),
        resolution: 512,
        detail: t('The faster pass for refining surface detail.'),
    },
    hi3d_1024: {
        name: t('Detail Refinement (1024)'),
        resolution: 1024,
        detail: t('A finer pass that takes longer and uses more GPU memory.'),
    },
};

const methods = [
    ['studio_768', t('Balanced Reconstruction'), t('Studio 768 · Rebuilds the cached surface for general use.')],
    ['wtivo_1024', t('Surface Closure'), t('WTiVo 1024 · Prioritizes closing surface gaps.')],
];
const number = new Intl.NumberFormat(formatLocale);

export function createHdMasterFinishing({api, startJob}) {
    const ui = dialog('hdMasterFinishing', t('HD Master Finishing'), '', '', 'hd-master-dialog');
    const modelName = el('p', 'hd-master-model');
    ui.element.querySelector('.studio-dialog-head h2').after(modelName);

    const form = el('form', 'hd-master-form');
    form.id = 'hdMasterFinishingForm';
    const options = el('fieldset', 'hd-master-options');
    options.append(el('legend', '', t('Reconstruction method')));
    const choices = methods.map(([value, title, description]) => {
        const control = el('input');
        control.type = 'radio';
        control.name = 'master_finishing';
        control.value = value;
        const copy = el('span', 'hd-master-method-copy');
        const detail = el('small');
        detail.id = 'hdMasterMethod-' + value;
        control.setAttribute('aria-label', title);
        control.setAttribute('aria-describedby', detail.id);
        copy.append(el('strong', '', title), detail);
        const label = el('label', 'hd-master-method');
        label.append(control, copy);
        options.append(label);
        return {value, description, control, detail};
    });
    const texture = select([], '');
    const metrics = el('dl', 'hd-master-metrics');
    const sourceResolution = el('dd');
    const ceiling = el('dd');
    metrics.append(el('dt', '', t('Cached source resolution')), sourceResolution, el('dt', '', t('Triangle ceiling')), ceiling);
    const nextStep = el('p', 'hint hd-master-next', t('Open the finished master and use Prepare → Game Copy from HD to make a lighter model.'));
    form.append(metrics, options, field(t('Texture resolution'), texture), nextStep);
    const submit = button(t('Create HD master'), 'layers', 'primary');
    submit.type = 'submit';
    submit.disabled = true;
    submit.setAttribute('form', form.id);
    const cancel = button(t('Cancel'), 'close', 'secondary', () => ui.close());
    ui.body.append(form);
    ui.foot.append(cancel, submit);

    let opening = 0;
    let sourceId = null;
    let pending = false;
    const current = version => ui.element.open && version === opening;
    function updateSubmit() {
        submit.disabled = form.hidden || pending || !texture.value
            || !choices.some(({control}) => control.checked && !control.disabled);
    }
    form.onchange = updateSubmit;
    form.onsubmit = async event => {
        event.preventDefault();
        if (submit.disabled || !sourceId) return;
        const selected = choices.find(({control}) => control.checked && !control.disabled);
        if (!selected) return;
        const version = opening;
        pending = true;
        updateSubmit();
        options.disabled = texture.disabled = true;
        ui.notice.textContent = t('Queueing HD master…');
        try {
            const result = await api(`/api/v1/models/${sourceId}/refinish`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({master_finishing: selected.value, texture_size: Number(texture.value)}),
            });
            if (current(version)) ui.close();
            await startJob(result.id);
        } catch (error) {
            if (current(version)) ui.notice.textContent = error.message;
        } finally {
            if (current(version)) {
                pending = false;
                options.disabled = texture.disabled = false;
                updateSubmit();
            }
        }
    };

    return {async open(job) {
        if (job?.state !== 'done' || ui.element.open) return;
        const version = ++opening;
        sourceId = job.id;
        pending = false;
        form.hidden = true;
        updateSubmit();
        modelName.textContent = job.metadata?.display_name || job.settings?.name || t('Selected model');
        ui.show();
        ui.notice.textContent = t('Checking the cached source…');
        try {
            const board = await api(`/api/v1/models/${job.id}/finishing-board`);
            if (!current(version)) return;
            const config = board.master_finishing;
            if (!config) {
                ui.notice.textContent = t('This Studio server does not provide HD Master Finishing.');
                return;
            }
            const textureSizes = (board.texture_sizes || []).filter(size => [1024, 2048, 4096].includes(size));
            texture.replaceChildren(...textureSizes.map(size => new Option(`${size / 1024}K`, size)));
            if (textureSizes.includes(config.default_texture_size)) texture.value = config.default_texture_size;
            for (const {value, description, control, detail} of choices) {
                const capability = config.methods?.[value];
                control.disabled = capability?.available !== true;
                control.checked = !control.disabled && value === config.default_method;
                detail.textContent = control.disabled ? (capability?.reason || t('Unavailable on this model.')) : description;
            }
            sourceResolution.textContent = Number.isFinite(config.source_resolution) ? `${config.source_resolution}³` : t('Unknown');
            ceiling.textContent = Number.isFinite(config.triangle_ceiling) ? number.format(config.triangle_ceiling) : t('Unknown');
            options.disabled = texture.disabled = false;
            form.hidden = false;
            ui.notice.textContent = '';
            updateSubmit();
        } catch (error) {
            if (current(version)) ui.notice.textContent = error.message;
        }
    }};
}
