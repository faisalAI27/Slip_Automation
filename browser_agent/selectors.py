"""Static, controlled DOM snapshot code used only by the Phase 4 inspector."""

# This script extracts semantics only. It never reads form values, submits forms,
# clicks elements, downloads files, or executes page-provided instructions.
PAGE_SNAPSHOT_SCRIPT = r"""
() => {
  const clean = (value) => {
    if (value === null || value === undefined) return null;
    const text = String(value).replace(/\s+/g, " ").trim();
    return text || null;
  };
  const visible = (element) => {
    if (!element || element.hidden) return false;
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const associatedLabel = (element) => {
    if (element.labels && element.labels.length) {
      return clean(Array.from(element.labels).map((label) => label.innerText).join(" "));
    }
    const parentLabel = element.closest("label");
    return parentLabel ? clean(parentLabel.innerText) : null;
  };

  const forms = Array.from(document.querySelectorAll("form"))
    .filter(visible)
    .map((form, index) => {
      const ref = `form_${index + 1}`;
      form.setAttribute("data-slip-ref", ref);
      return {
        ref,
        name: clean(form.getAttribute("name") || form.getAttribute("id")),
        method: clean(form.getAttribute("method")),
        action: clean(form.action),
      };
    });

  const inputs = Array.from(
    document.querySelectorAll("input:not([type=hidden]), textarea, select")
  )
    .filter(visible)
    .map((element, index) => {
      const ref = `input_${index + 1}`;
      element.setAttribute("data-slip-ref", ref);
      const tag = element.tagName.toLowerCase();
      return {
        ref,
        tag,
        type: tag === "select" ? "select" : tag === "textarea" ? "textarea" : clean(element.type),
        name: clean(element.getAttribute("name")),
        label: associatedLabel(element),
        placeholder: clean(element.getAttribute("placeholder")),
        ariaLabel: clean(element.getAttribute("aria-label")),
        required: Boolean(element.required || element.getAttribute("aria-required") === "true"),
        disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
        readOnly: Boolean(element.readOnly),
        autocomplete: clean(element.getAttribute("autocomplete")),
        formRef: element.form ? clean(element.form.getAttribute("data-slip-ref")) : null,
      };
    });

  const buttons = Array.from(
    document.querySelectorAll('button, input[type="submit"], input[type="button"], input[type="reset"], [role="button"]')
  )
    .filter((element) => {
      if (!visible(element)) return false;
      const className = typeof element.className === "string" ? element.className : "";
      return !/(?:swiper|carousel|slideshow|slick)[-_ ]/i.test(className);
    })
    .map((element, index) => {
      const ref = `button_${index + 1}`;
      element.setAttribute("data-slip-ref", ref);
      return {
        ref,
        text: clean(
          element.innerText || element.value || element.getAttribute("aria-label") || element.getAttribute("title")
        ),
        type: clean(element.getAttribute("type") || element.getAttribute("role")),
        disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
        formRef: element.form ? clean(element.form.getAttribute("data-slip-ref")) : null,
      };
    });

  const links = Array.from(document.querySelectorAll("a[href]"))
    .filter(visible)
    .map((element, index) => {
      const ref = `link_${index + 1}`;
      element.setAttribute("data-slip-ref", ref);
      return {
        ref,
        text: clean(element.innerText || element.getAttribute("aria-label") || element.getAttribute("title")),
        url: clean(element.href),
      };
    });

  const messageSelectors = [
    '[role="alert"]',
    '[aria-live="assertive"]',
    '.alert-danger',
    '.error-message',
    '.validation-error'
  ];
  const messages = Array.from(document.querySelectorAll(messageSelectors.join(",")))
    .filter(visible)
    .map((element) => clean(element.innerText))
    .filter(Boolean);

  const captchaNodes = Array.from(document.querySelectorAll(
    '[id*="captcha" i], [class*="captcha" i], iframe[src*="recaptcha" i], iframe[src*="hcaptcha" i], [data-sitekey]'
  )).filter(visible).length;
  const iframeHints = Array.from(document.querySelectorAll("iframe"))
    .map((frame) => clean(`${frame.title || ""} ${frame.name || ""} ${frame.src || ""}`))
    .filter(Boolean);
  const main = document.querySelector("main, [role=main]") || document.body;

  return {
    forms,
    inputs,
    buttons,
    links,
    messages,
    captchaNodes,
    iframeHints,
    visibleText: clean(main ? main.innerText : ""),
  };
}
"""
