"""Generic form introspection and filling.

Rather than hand-writing selectors per ATS, we stamp every control in the
form with a `data-ja-field` index in the page, read back a structured
description of each one, decide answers in Python, then act on the stamps.
Stamps survive re-renders better than generated CSS selectors and let radio
groups be described as one question with N clickable options.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

# Stamps every control and returns a description of each question.
# Radio/checkbox groups collapse into a single entry whose options carry the
# stamp of the individual input to click.
STAMP_AND_READ_JS = r"""
(rootSel) => {
  const root = rootSel ? document.querySelector(rootSel) : document.body;
  if (!root) return [];
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    if (el.type === 'file') return true;           // often visually hidden
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' &&
           (r.width > 0 || r.height > 0);
  };
  const labelText = el => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return clean(l.innerText || l.textContent);
    }
    const wrap = el.closest('label');
    if (wrap) return clean(wrap.innerText);
    const ref = el.getAttribute('aria-labelledby');
    if (ref) {
      const parts = ref.split(/\s+/).map(i => document.getElementById(i))
                       .filter(Boolean).map(p => clean(p.innerText));
      if (parts.join(' ').trim()) return clean(parts.join(' '));
    }
    const fs = el.closest('fieldset');
    if (fs) {
      const lg = fs.querySelector('legend');
      if (lg) return clean(lg.innerText);
    }
    for (const sel of ['.field', '.form-group', '.application-field',
                       '[class*="question"]', '[class*="field"]']) {
      const grp = el.closest(sel);
      if (grp) {
        const l = grp.querySelector('label, legend, .label');
        if (l && !l.contains(el)) return clean(l.innerText);
      }
    }
    return clean(el.getAttribute('aria-label') || el.getAttribute('placeholder')
                 || el.name || '');
  };
  const isRequired = el => {
    if (el.required || el.getAttribute('aria-required') === 'true') return true;
    const grp = el.closest('.field, .form-group, fieldset, [class*="field"]');
    return !!(grp && /\*|\(required\)/i.test(grp.innerText || ''));
  };

  let n = 0;
  const out = [];
  const groups = new Map();
  const controls = root.querySelectorAll(
    "input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea");

  for (const el of controls) {
    if (!visible(el)) continue;
    const type = (el.type || '').toLowerCase();
    const idx = n++;
    el.setAttribute('data-ja-field', String(idx));

    if (type === 'radio' || type === 'checkbox') {
      const key = type + ':' + (el.name || labelText(el));
      // The option's own text; fall back to its value.
      let optText = '';
      const own = el.closest('label') ||
                  (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
      if (own) optText = clean(own.innerText);
      if (!optText) optText = clean(el.value);
      if (!groups.has(key)) {
        const fs = el.closest('fieldset');
        let q = '';
        if (fs) { const lg = fs.querySelector('legend'); if (lg) q = clean(lg.innerText); }
        if (!q) {
          const grp = el.closest('.field, .form-group, [class*="question"]');
          if (grp) { const l = grp.querySelector('label, legend'); if (l) q = clean(l.innerText); }
        }
        const entry = { idx, kind: type, label: q || optText, required: isRequired(el),
                        value: '', options: [], option_idx: [] };
        groups.set(key, entry);
        out.push(entry);
      }
      const entry = groups.get(key);
      entry.options.push(optText);
      entry.option_idx.push(idx);
      if (el.checked) entry.value = optText;
      continue;
    }

    if (el.tagName === 'SELECT') {
      out.push({
        idx, kind: 'select', label: labelText(el), required: isRequired(el),
        value: clean(el.selectedOptions[0] ? el.selectedOptions[0].textContent : ''),
        options: Array.from(el.options).map(o => clean(o.textContent))
                      .filter(t => t.length > 0),
        option_idx: [],
      });
      continue;
    }

    const kind = el.tagName === 'TEXTAREA' ? 'textarea'
               : type === 'file' ? 'file' : 'text';
    out.push({ idx, kind, label: labelText(el), required: isRequired(el),
               value: kind === 'file' ? '' : clean(el.value),
               options: [], option_idx: [] });
  }
  return out;
}
"""

# Some ATSs use listbox widgets (div-based) instead of <select>. Read their
# trigger buttons so we can at least report them rather than silently skip.
CUSTOM_SELECT_JS = r"""
() => Array.from(document.querySelectorAll(
        '[role=combobox], [role=listbox], .select__control'))
      .filter(el => el.offsetParent !== null)
      .length
"""


@dataclass
class FormField:
    idx: int
    kind: str  # text | textarea | select | radio | checkbox | file
    label: str
    required: bool = False
    value: str = ""
    options: list[str] = dc_field(default_factory=list)
    option_idx: list[int] = dc_field(default_factory=list)

    @property
    def is_answered(self) -> bool:
        return bool(str(self.value).strip())

    @property
    def question(self) -> str:
        return self.label.strip()


def read_fields(page, root_selector: str | None = None) -> list[FormField]:
    """Stamp and describe every visible control (optionally within a root)."""
    raw = page.evaluate(STAMP_AND_READ_JS, root_selector)
    fields: list[FormField] = []
    for item in raw or []:
        fields.append(FormField(
            idx=int(item["idx"]),
            kind=str(item["kind"]),
            label=str(item.get("label") or ""),
            required=bool(item.get("required")),
            value=str(item.get("value") or ""),
            options=[str(o) for o in item.get("options") or []],
            option_idx=[int(i) for i in item.get("option_idx") or []],
        ))
    return fields


def locator_for(page, idx: int):
    return page.locator(f"[data-ja-field='{idx}']")


def option_index(options: list[str], answer: str) -> int | None:
    """Match an answer to one of a control's options, loosely."""
    want = answer.strip().lower()
    if not want:
        return None
    for i, opt in enumerate(options):
        if opt.strip().lower() == want:
            return i
    for i, opt in enumerate(options):
        low = opt.strip().lower()
        if low and (want in low or low in want):
            return i
    # Yes/No radios sometimes render as "Yes, I am authorized..." etc.
    if want in ("yes", "no"):
        for i, opt in enumerate(options):
            if opt.strip().lower().startswith(want):
                return i
    return None


def match_option(options: list[str], answer: str) -> str | None:
    """The option text matching `answer`, or None when nothing fits."""
    i = option_index(options, answer)
    return options[i] if i is not None else None


def fill_field(page, field: FormField, answer: str) -> bool:
    """Apply `answer` to one field. Returns True when the control was set."""
    target = locator_for(page, field.idx)
    if field.kind in ("text", "textarea"):
        target.fill(answer)
        return True
    if field.kind == "select":
        i = option_index(field.options, answer)
        if i is None:
            return False
        target.select_option(label=field.options[i])
        return True
    if field.kind in ("radio", "checkbox"):
        i = option_index(field.options, answer)
        if i is None or i >= len(field.option_idx):
            return False
        option = locator_for(page, field.option_idx[i])
        # The input itself is often visually hidden behind a styled label.
        try:
            option.check(timeout=4000)
        except Exception:
            option.click(force=True, timeout=4000)
        return True
    return False


def attach_file(page, field: FormField, path) -> bool:
    locator_for(page, field.idx).set_input_files(str(path))
    return True
