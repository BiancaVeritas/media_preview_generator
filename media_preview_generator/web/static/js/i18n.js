/*!
 * Chinese UI for Media Preview Generator.
 *
 * The app has no gettext markers, so the catalogue is keyed by the English text
 * itself: every text node and every user-facing attribute whose whole value is a
 * key is replaced. Templates are translated when the page is first shown; text
 * the app writes later (dialogs, toasts, live status) is translated as it lands,
 * through a MutationObserver.
 *
 * Load `i18n/zh-CN.js` before this file: it defines `window.__MPG_I18N__` for
 * `zh-CN` and `window.__MPG_I18N_PATTERNS__` for the sentences that carry live
 * values ("Retry 2/5"). A page with no catalogue stays English.
 *
 * The language is per browser (`localStorage.mpg_lang`), default `zh-CN`. The
 * navbar's translate button reloads the page with the other one.
 */
(function () {
    "use strict";

    var LANG_KEY = "mpg_lang";
    var COOKIE_NAME = "mpg_lang";
    var DEFAULT_LANG = "zh-CN";
    var STORE_ATTRIBUTES = [
        "title",
        "placeholder",
        "aria-label",
        "alt",
        "data-bs-title",
        "data-bs-original-title",
        "data-tooltip",
        "data-explain-title"
    ];
    var SKIP_SELECTOR = "script,style,code,pre,textarea,kbd,samp,.no-i18n,[data-i18n='off'],[translate='no']";

    function savedLang() {
        try {
            var stored = localStorage.getItem(LANG_KEY);
            if (stored === "zh-CN" || stored === "en") {
                return stored;
            }
        } catch (error) {
            /* localStorage blocked: use the default */
        }
        return DEFAULT_LANG;
    }

    var lang = savedLang();
    var dict = (window.__MPG_I18N__ || {})[lang] || {};
    var rawPatterns = (window.__MPG_I18N_PATTERNS__ || {})[lang] || [];
    var hasCatalogue = Object.keys(dict).length > 0;

    function normalize(text) {
        return String(text).replace(/\s+/g, " ").trim();
    }

    function escapeRegExp(text) {
        return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    var patterns = rawPatterns.map(function (entry) {
        var source = entry[0];
        var target = entry[1];
        var slots = 0;
        var regex = escapeRegExp(source).replace(/\\?\{(\d+)\\?\}/g, function (match, index) {
            slots = Math.max(slots, Number(index) + 1);
            return "(.+?)";
        });
        var prefix = source.split("{")[0];
        try {
            return { re: new RegExp("^" + regex + "$"), target: target, slots: slots, prefix: prefix };
        } catch (error) {
            return null;
        }
    }).filter(Boolean);

    function fillPattern(pattern, match) {
        var out = pattern.target;
        for (var i = 1; i <= pattern.slots; i += 1) {
            var value = match[i] || "";
            // A slot holding a label ("Dashboard - …") is translated too; numbers and paths pass through.
            var label = dict[normalize(value)];
            out = out.split("{" + (i - 1) + "}").join(label !== undefined ? label : value);
        }
        return out;
    }

    // A GPU/language/level name is not prose: the pattern scan would turn "CPU" into "个 CPU".
    var NAMES = { CPU: 1, GPU: 1, English: 1, Plex: 1, Emby: 1, Jellyfin: 1, Sonarr: 1, Radarr: 1, Tdarr: 1,
        NVIDIA: 1, Vulkan: 1, CUDA: 1, UTC: 1, Webhook: 1, "Plex Pass": 1, "1 CPU": 1, "1 GPU": 1 };

    function lookup(text) {
        var key = normalize(text);
        // Numbers, paths and punctuation can't be labels; skip the pattern scan for them.
        if (!key || !/[A-Za-z]/.test(key)) {
            return null;
        }
        var direct = dict[key];
        if (direct !== undefined) {
            return direct;
        }
        if (NAMES[key] || /^v?\d+\.\d+/.test(key)) {
            return null;
        }
        for (var i = 0; i < patterns.length; i += 1) {
            var pattern = patterns[i];
            if (pattern.prefix && key.lastIndexOf(pattern.prefix, 0) !== 0) {
                continue;
            }
            var match = pattern.re.exec(key);
            if (match) {
                return fillPattern(pattern, match);
            }
        }
        return null;
    }

    function translateValue(value) {
        if (!value) {
            return null;
        }
        var lead = value.match(/^\s*/)[0];
        var tail = value.match(/\s*$/)[0];
        var body = value.slice(lead.length, value.length - tail.length);
        if (!body) {
            return null;
        }
        var hit = lookup(body);
        return hit === null || hit === body ? null : lead + hit + tail;
    }

    function skipped(element) {
        return !!(element && element.closest && element.closest(SKIP_SELECTOR));
    }

    function translateText(node) {
        if (!node || !node.parentElement || skipped(node.parentElement)) {
            return;
        }
        var value = translateValue(node.nodeValue);
        if (value !== null) {
            node.nodeValue = value;
        }
    }

    function translateAttributes(element) {
        if (!element.getAttribute) {
            return;
        }
        for (var i = 0; i < STORE_ATTRIBUTES.length; i += 1) {
            var name = STORE_ATTRIBUTES[i];
            var current = element.getAttribute(name);
            if (!current) {
                continue;
            }
            var value = translateValue(current);
            if (value !== null) {
                element.setAttribute(name, value);
            }
        }
        if (element.tagName === "INPUT") {
            var type = (element.getAttribute("type") || "").toLowerCase();
            if (type === "submit" || type === "button" || type === "reset") {
                var label = translateValue(element.value);
                if (label !== null) {
                    element.value = label;
                }
            }
        }
    }

    function translateTree(root) {
        if (!root) {
            return;
        }
        if (root.nodeType === 3) {
            translateText(root);
            return;
        }
        // A DocumentFragment (the template used for markup) has no parentElement of its own.
        if (root.nodeType !== 1 && root.nodeType !== 11) {
            return;
        }
        if (skipped(root)) {
            return;
        }
        translateAttributes(root);
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
            acceptNode: function (node) {
                if (node.nodeType === 1 && skipped(node)) {
                    return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        var node = walker.nextNode();
        while (node) {
            if (node.nodeType === 3) {
                translateText(node);
            } else {
                translateAttributes(node);
            }
            node = walker.nextNode();
        }
    }

    function translateTitle() {
        if (!document.title) {
            return;
        }
        var hit = lookup(document.title);
        if (hit !== null && hit !== document.title) {
            document.title = hit;
        }
    }

    /* ---- Translating markup before it reaches the page --------------------------------

     * The observer can only translate after the browser has painted, which is the flash of
     * English this fixes. Markup the app builds itself is translated here instead, in the
     * innerHTML setter, so it is Chinese the first time it is ever rendered. */

    // The native setters, captured before they are wrapped: calling the wrapped one from inside a hook would recurse.
    var nativeInnerHTML = null;
    var nativeTextContent = null;

    function translateMarkup(markup) {
        if (typeof markup !== "string" || !markup || markup.indexOf("<") < 0) {
            return translateMarkupText(markup);
        }
        if (!nativeInnerHTML || !/[A-Za-z]{3}/.test(markup)) {
            return markup;
        }
        try {
            var template = document.createElement("template");
            nativeInnerHTML.set.call(template, markup);
            translateTree(template.content);
            return nativeInnerHTML.get.call(template);
        } catch (error) {
            return markup;
        }
    }

    // A plain string written with textContent: translated only when it is a label the catalogue knows.
    function translateMarkupText(value) {
        if (typeof value !== "string" || value.length < 3 || value.length > 200) {
            return value;
        }
        var hit = lookup(value);
        return hit === null ? value : hit;
    }

    function installMarkupHooks() {
        if (lang !== "zh-CN" || !hasCatalogue || window.__mpgMarkupHooks) {
            return;
        }
        window.__mpgMarkupHooks = true;
        var elementProto = window.Element && window.Element.prototype;
        if (!elementProto) {
            return;
        }
        var innerHtml = Object.getOwnPropertyDescriptor(elementProto, "innerHTML");
        if (innerHtml && innerHtml.set) {
            nativeInnerHTML = innerHtml;
            Object.defineProperty(elementProto, "innerHTML", {
                configurable: true,
                enumerable: innerHtml.enumerable,
                get: innerHtml.get,
                set: function (value) {
                    innerHtml.set.call(this, translateMarkup(String(value)));
                }
            });
        }
        var textContent = Object.getOwnPropertyDescriptor(window.Node.prototype, "textContent");
        if (textContent && textContent.set) {
            nativeTextContent = textContent;
            Object.defineProperty(window.Node.prototype, "textContent", {
                configurable: true,
                enumerable: textContent.enumerable,
                get: textContent.get,
                set: function (value) {
                    textContent.set.call(this, translateMarkupText(value));
                }
            });
        }
        if (typeof elementProto.insertAdjacentHTML === "function") {
            var insertAdjacentHTML = elementProto.insertAdjacentHTML;
            elementProto.insertAdjacentHTML = function (position, markup) {
                return insertAdjacentHTML.call(this, position, translateMarkup(String(markup)));
            };
        }
    }

    var OBSERVE_OPTIONS = {
        childList: true,
        subtree: true,
        characterData: true,
        // The app also writes titles and placeholders (tooltips, badges) after load. A translated value is no longer a
        // key, so the write this makes cannot trigger another translation.
        attributes: true,
        attributeFilter: ["title", "placeholder", "aria-label", "alt", "data-bs-title", "data-bs-original-title"]
    };

    var observer = new MutationObserver(function (mutations) {
        observer.disconnect();
        try {
            for (var i = 0; i < mutations.length; i += 1) {
                var mutation = mutations[i];
                if (mutation.type === "characterData") {
                    translateText(mutation.target);
                    continue;
                }
                if (mutation.type === "attributes") {
                    translateAttributes(mutation.target);
                    continue;
                }
                for (var j = 0; j < mutation.addedNodes.length; j += 1) {
                    translateTree(mutation.addedNodes[j]);
                }
            }
            translateTitle();
        } finally {
            observer.observe(document.body, OBSERVE_OPTIONS);
        }
    });

    // Exposed for the catalogue test and for other scripts that build text themselves.
    window.__mpgI18n = { lookup: lookup, translateValue: translateValue, language: lang };

    // Browser dialogs are not DOM, so they need their own lookup.
    function translateDialogs() {
        if (lang !== "zh-CN" || !hasCatalogue) {
            return;
        }
        ["confirm", "alert", "prompt"].forEach(function (name) {
            var original = window[name];
            if (typeof original !== "function" || original.__mpgWrapped) {
                return;
            }
            var wrapped = function (message, defaultValue) {
                var hit = typeof message === "string" ? lookup(message) : null;
                return original.call(window, hit === null ? message : hit, defaultValue);
            };
            wrapped.__mpgWrapped = true;
            window[name] = wrapped;
        });
    }

    function start() {
        if (lang === "en" || !hasCatalogue) {
            document.documentElement.setAttribute("lang", "en");
            return;
        }
        document.documentElement.setAttribute("lang", "zh-CN");
        translateDialogs();
        translateTree(document.body);
        translateTitle();
        observer.observe(document.body, OBSERVE_OPTIONS);
        window.mpgTranslate = translateTree;
    }

    function wireLanguageButton() {
        var button = document.getElementById("langToggleBtn");
        var label = document.getElementById("langToggleLabel");
        if (label) {
            label.textContent = lang === "zh-CN" ? "English" : "中文";
        }
        if (!button) {
            return;
        }
        button.addEventListener("click", function () {
            var next = lang === "zh-CN" ? "en" : "zh-CN";
            try {
                localStorage.setItem(LANG_KEY, next);
            } catch (error) {
                /* best-effort; the page still reloads in the default language */
            }
            // The server translates each page from this cookie, so it is set before the reload as well.
            try {
                document.cookie = COOKIE_NAME + "=" + next + "; Path=/; Max-Age=31536000; SameSite=Lax";
            } catch (error) {
                /* the reload then keeps the language the server was already told */
            }
            window.location.reload();
        });
    }

    // Keep the server's cookie and this browser's choice in step (an older browser may hold only the localStorage key).
    function syncCookies() {
        try {
            document.cookie = COOKIE_NAME + "=" + lang + "; Path=/; Max-Age=31536000; SameSite=Lax";
        } catch (error) {
            /* nothing to do: the server falls back to its default */
        }
    }

    syncCookies();
    // Before anything writes markup: app.js builds most of the dashboard with innerHTML.
    installMarkupHooks();

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            start();
            wireLanguageButton();
        });
    } else {
        start();
        wireLanguageButton();
    }
})();
