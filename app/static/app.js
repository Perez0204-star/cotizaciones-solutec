(function () {
  function onIdle(callback) {
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(() => callback(), { timeout: 500 });
      return;
    }
    window.setTimeout(callback, 32);
  }

  function parseJsonScript(id) {
    const node = document.getElementById(id);
    if (!node) return [];
    try {
      return JSON.parse(node.textContent || "[]");
    } catch (error) {
      return [];
    }
  }

  function formatMoney(value, roundingMode) {
    const decimals = roundingMode === "2dec" ? 2 : 0;
    return new Intl.NumberFormat("es-CO", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(Number(value || 0));
  }

  function roundValue(value, mode) {
    const amount = Number(value || 0);
    if (mode === "2dec") return Math.round(amount * 100) / 100;
    if (mode === "nearest10") return Math.round(amount / 10) * 10;
    if (mode === "nearest100") return Math.round(amount / 100) * 100;
    return Math.round(amount);
  }

  function clampMarginPercent(value) {
    const amount = Number(value || 100);
    if (!Number.isFinite(amount)) return 100;
    return Math.min(100, Math.max(1, Math.round(amount * 100) / 100));
  }

  function formatMarginPercent(value) {
    const normalized = clampMarginPercent(value);
    if (Number.isInteger(normalized)) return String(normalized);
    return String(normalized);
  }

  function initCatalogForm() {
    const form = document.querySelector('[data-page-form="catalog"]');
    if (!form) return;

    const modeField = document.getElementById("catalog-pricing-mode");
    const costField = document.getElementById("catalog-cost");
    const marginField = document.getElementById("catalog-margin");
    const markupField = document.getElementById("catalog-markup");
    const manualField = document.getElementById("catalog-manual-price");
    const output = document.getElementById("catalog-price-preview");
    const roundingMode = form.dataset.roundingMode || "integer";

    function recompute() {
      const cost = Number(costField.value || 0);
      const margin = Number(marginField.value || 0) / 100;
      const markup = Number(markupField.value || 0) / 100;
      let price = Number(manualField.value || 0);

      if (modeField.value === "MARGIN") {
        price = margin >= 1 ? 0 : cost / (1 - margin);
      } else if (modeField.value === "MARKUP") {
        price = cost * (1 + markup);
      }

      output.textContent = formatMoney(roundValue(price, roundingMode), roundingMode);
    }

    [modeField, costField, marginField, markupField, manualField].forEach((field) => {
      field.addEventListener("input", recompute);
      field.addEventListener("change", recompute);
    });

    recompute();
  }

  function initCopyButtons() {
    const buttons = Array.from(document.querySelectorAll("[data-copy-text]"));
    if (!buttons.length) return;

    buttons.forEach((button) => {
      const original = button.textContent;
      button.addEventListener("click", async () => {
        const text = button.dataset.copyText || "";
        if (!text) return;

        try {
          if (navigator.share && button.dataset.useShare === "1") {
            await navigator.share({ url: text });
          } else if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
          } else {
            const helper = document.createElement("textarea");
            helper.value = text;
            document.body.appendChild(helper);
            helper.select();
            document.execCommand("copy");
            helper.remove();
          }

          button.textContent = "Enlace copiado";
          window.setTimeout(() => {
            button.textContent = original;
          }, 1600);
        } catch (error) {
          button.textContent = "No se pudo copiar";
          window.setTimeout(() => {
            button.textContent = original;
          }, 1600);
        }
      });
    });
  }

  function initVideoPlayers() {
    const toggles = Array.from(document.querySelectorAll("[data-video-toggle]"));
    if (!toggles.length) return;

    toggles.forEach((button) => {
      button.addEventListener("click", () => {
        const target = document.getElementById(button.dataset.videoToggle || "");
        if (!target) return;

        const iframe = target.querySelector("iframe");
        if (iframe && !iframe.src && iframe.dataset.src) {
          iframe.src = iframe.dataset.src;
        }

        target.classList.toggle("hidden");
        button.textContent = target.classList.contains("hidden") ? "Ver video" : "Ocultar video";
      });
    });
  }

  function initCatalogGalleries() {
    const galleries = Array.from(document.querySelectorAll("[data-gallery]"));
    if (!galleries.length) return;

    function uniqueSources(values) {
      return values.filter((value, index, list) => value && list.indexOf(value) === index);
    }

    function ensureLightbox() {
      let overlay = document.querySelector("[data-gallery-lightbox]");
      if (overlay) return overlay;

      overlay = document.createElement("div");
      overlay.className = "catalog-lightbox hidden";
      overlay.dataset.galleryLightbox = "1";
      overlay.innerHTML = `
        <div class="catalog-lightbox-backdrop" data-lightbox-close></div>
        <div class="catalog-lightbox-dialog" role="dialog" aria-modal="true" aria-label="Visor de imagenes">
          <button class="catalog-lightbox-close" type="button" data-lightbox-close aria-label="Cerrar">x</button>
          <button class="catalog-lightbox-nav prev" type="button" data-lightbox-prev aria-label="Imagen anterior">&lsaquo;</button>
          <img class="catalog-lightbox-image" alt="">
          <button class="catalog-lightbox-nav next" type="button" data-lightbox-next aria-label="Imagen siguiente">&rsaquo;</button>
          <div class="catalog-lightbox-footer">
            <strong data-lightbox-title></strong>
            <span data-lightbox-count></span>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      return overlay;
    }

    function openLightbox(images, startIndex, title) {
      if (!images.length) return;

      const overlay = ensureLightbox();
      const image = overlay.querySelector(".catalog-lightbox-image");
      const titleNode = overlay.querySelector("[data-lightbox-title]");
      const countNode = overlay.querySelector("[data-lightbox-count]");
      const prevButton = overlay.querySelector("[data-lightbox-prev]");
      const nextButton = overlay.querySelector("[data-lightbox-next]");
      let currentIndex = Math.max(0, Math.min(startIndex, images.length - 1));

      function render() {
        image.src = images[currentIndex];
        image.alt = title || "Imagen del producto";
        titleNode.textContent = title || "Galeria del producto";
        countNode.textContent = `${currentIndex + 1} de ${images.length}`;
        prevButton.disabled = images.length <= 1;
        nextButton.disabled = images.length <= 1;
      }

      function close() {
        overlay.classList.add("hidden");
        document.removeEventListener("keydown", handleKeys);
      }

      function next() {
        currentIndex = (currentIndex + 1) % images.length;
        render();
      }

      function prev() {
        currentIndex = (currentIndex - 1 + images.length) % images.length;
        render();
      }

      function handleKeys(event) {
        if (event.key === "Escape") close();
        if (event.key === "ArrowRight") next();
        if (event.key === "ArrowLeft") prev();
      }

      overlay.querySelectorAll("[data-lightbox-close]").forEach((button) => {
        button.onclick = close;
      });
      prevButton.onclick = prev;
      nextButton.onclick = next;

      render();
      overlay.classList.remove("hidden");
      document.addEventListener("keydown", handleKeys);
    }

    galleries.forEach((gallery) => {
      if (gallery.dataset.galleryReady === "1") return;
      gallery.dataset.galleryReady = "1";

      const main = gallery.querySelector("[data-gallery-main]");
      const thumbs = Array.from(gallery.querySelectorAll("[data-gallery-thumb]"));
      const openButton = gallery.querySelector("[data-gallery-open]");
      if (!main) return;

      const sources = uniqueSources([
        main.tagName === "IMG" ? main.getAttribute("src") : "",
        ...thumbs.map((thumb) => thumb.dataset.galleryThumb || ""),
      ]);
      const title = gallery.dataset.galleryTitle || (main.getAttribute("alt") || "");
      let activeIndex = 0;

      if (main.tagName === "IMG") {
        main.setAttribute("role", "button");
        main.setAttribute("tabindex", "0");
        main.classList.add("is-clickable");
        main.addEventListener("click", () => openLightbox(sources, activeIndex, title));
        main.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openLightbox(sources, activeIndex, title);
          }
        });
      }

      if (openButton) {
        openButton.addEventListener("click", () => openLightbox(sources, activeIndex, title));
      }

      thumbs.forEach((thumb) => {
        thumb.addEventListener("click", () => {
          const selectedSrc = thumb.dataset.galleryThumb || "";
          if (main.tagName === "IMG") {
            main.src = selectedSrc || main.src;
          }
          activeIndex = Math.max(0, sources.indexOf(selectedSrc));
          thumbs.forEach((item) => item.classList.remove("active"));
          thumb.classList.add("active");
          openLightbox(sources, activeIndex, title);
        });
      });
    });
  }

  function initSharedCatalogCart() {
    const panel = document.querySelector("[data-cart-panel]");
    if (!panel) return;
    if (panel.dataset.cartReady === "1") return;
    panel.dataset.cartReady = "1";

    const itemsNode = panel.querySelector("[data-cart-items]");
    const totalNode = panel.querySelector("[data-cart-total]");
    const checkoutButton = panel.querySelector("[data-cart-whatsapp]");
    const whatsappNumber = panel.dataset.whatsapp || "";
    const sellerQuoteButton = panel.querySelector("[data-cart-seller-quote]");
    const sellerInvoiceButton = panel.querySelector("[data-cart-seller-invoice]");
    const orderNameField = panel.querySelector("[data-order-name]");
    const orderPhoneField = panel.querySelector("[data-order-phone]");
    const orderAddressField = panel.querySelector("[data-order-address]");
    const orderFeedback = panel.querySelector("[data-order-feedback]");
    const cart = new Map();

    function moneyLabel(value) {
      return formatMoney(value, "integer");
    }

    function cartPayload(items) {
      const payload = items.map((item) => ({
        id: item.id,
        qty: item.qty,
      }));
      return btoa(JSON.stringify(payload))
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/g, "");
    }

    function updateSellerLinks(items) {
      const encodedCart = items.length ? cartPayload(items) : "";
      const targets = [
        { button: sellerQuoteButton, path: "/quotes/new?mode=quote" },
        { button: sellerInvoiceButton, path: "/quotes/new?mode=invoice" },
      ];

      targets.forEach(({ button, path }) => {
        if (!button) return;
        if (!encodedCart) {
          button.href = path;
          button.setAttribute("aria-disabled", "true");
          button.classList.add("is-disabled");
          return;
        }
        button.href = `${path}&cart=${encodeURIComponent(encodedCart)}`;
        button.setAttribute("aria-disabled", "false");
        button.classList.remove("is-disabled");
      });
    }

    function showOrderFeedback(message, type = "error") {
      if (!orderFeedback) return;
      orderFeedback.textContent = message;
      orderFeedback.classList.remove("hidden", "success", "error");
      orderFeedback.classList.add(type);
    }

    function clearOrderFeedback() {
      if (!orderFeedback) return;
      orderFeedback.textContent = "";
      orderFeedback.classList.add("hidden");
      orderFeedback.classList.remove("success", "error");
    }

    function normalizeSimpleName(value) {
      return (value || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .trim();
    }

    function inferInterestWord(customerName) {
      const firstName = normalizeSimpleName((customerName || "").split(/\s+/)[0] || "");
      if (!firstName) return "interesado(a)";

      const femaleNames = new Set([
        "maria", "ana", "laura", "paula", "andrea", "carolina", "luisa", "luisafernanda",
        "daniela", "valentina", "sofia", "camila", "diana", "angela", "gloria", "patricia",
        "adriana", "monica", "karen", "natalia", "juliana", "ximena", "yesenia", "yuliana",
        "viviana", "claudia", "lina", "marcela", "sandra", "tatiana", "rosa", "martha",
      ]);
      const maleNames = new Set([
        "carlos", "juan", "luis", "jose", "andres", "sebastian", "daniel", "alejandro",
        "mateo", "david", "jorge", "miguel", "felipe", "santiago", "kevin", "julian",
        "cristian", "jhon", "john", "edwin", "wilson", "oscar", "hernan", "ricardo",
        "alberto", "pedro", "rafael", "samuel", "camilo", "diego", "emanuel", "sergio",
      ]);

      if (femaleNames.has(firstName)) return "interesada";
      if (maleNames.has(firstName)) return "interesado";
      if (firstName.endsWith("a")) return "interesada";
      if (firstName.endsWith("o")) return "interesado";
      return "interesado(a)";
    }

    async function createCatalogOrder(items) {
      const customerName = (orderNameField?.value || "").trim();
      const customerPhone = (orderPhoneField?.value || "").trim();
      const customerAddress = (orderAddressField?.value || "").trim();

      if (!customerName) {
        showOrderFeedback("Escribe el nombre para registrar el pedido.");
        orderNameField?.focus();
        return null;
      }
      if (!customerAddress) {
        showOrderFeedback("Escribe la direccion o ubicacion para registrar el pedido.");
        orderAddressField?.focus();
        return null;
      }

      const response = await fetch("/catalog/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_name: customerName,
          customer_phone: customerPhone,
          customer_address: customerAddress,
          items: items.map((item) => ({ id: item.id, qty: item.qty })),
        }),
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showOrderFeedback(data.error || "No fue posible guardar el pedido.");
        return null;
      }

      showOrderFeedback(`Pedido ${data.order_number} guardado. Abriendo WhatsApp...`, "success");
      return {
        orderNumber: data.order_number,
        quoteId: data.quote_id,
        quoteNumber: data.quote_number,
        subtotal: Number(data.subtotal || 0),
        taxAmount: Number(data.tax_amount || 0),
        total: Number(data.total || 0),
        customerName,
        customerPhone,
        customerAddress,
      };
    }

    function renderCart() {
      const items = Array.from(cart.values());
      const total = items.reduce((sum, item) => sum + item.qty * item.price, 0);
      updateSellerLinks(items);

      if (!itemsNode || !totalNode || !checkoutButton) return;

      totalNode.textContent = moneyLabel(total);
      checkoutButton.disabled = !items.length || !whatsappNumber;

      if (!items.length) {
        itemsNode.innerHTML = '<p class="catalog-cart-empty">Agrega productos para preparar el mensaje de WhatsApp.</p>';
        return;
      }

      itemsNode.innerHTML = "";
      items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "catalog-cart-row";
        row.innerHTML = `
          <div>
            <strong>${item.name}</strong>
            <span>${item.qty} x ${item.priceLabel}</span>
          </div>
          <div class="catalog-cart-controls">
            <button type="button" data-cart-dec="${item.id}" aria-label="Restar">-</button>
            <span>${item.qty}</span>
            <button type="button" data-cart-inc="${item.id}" aria-label="Sumar">+</button>
          </div>
        `;
        itemsNode.appendChild(row);
      });
    }

    function addItemFromButton(button) {
      const id = button.dataset.id || "";
      if (!id) return;

      const stock = Number(button.dataset.stock || 0);
      const current = cart.get(id);
      const nextQty = current ? current.qty + 1 : 1;
      if (stock > 0 && nextQty > stock) return;

      cart.set(id, {
        id,
        name: button.dataset.name || "Producto",
        price: Number(button.dataset.price || 0),
        priceLabel: button.dataset.priceLabel || moneyLabel(button.dataset.price || 0),
        stock,
        unit: button.dataset.unit || "UND",
        qty: nextQty,
      });
      renderCart();
    }

    document.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      const button = target.closest("[data-cart-add]");
      if (!button || button.disabled) return;

      addItemFromButton(button);
      const original = button.textContent;
      button.textContent = "Agregado al carrito";
      window.setTimeout(() => {
        button.textContent = original;
      }, 1200);
    });

    if (itemsNode) {
      itemsNode.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;

        const incId = target.dataset.cartInc;
        const decId = target.dataset.cartDec;
        const id = incId || decId;
        if (!id || !cart.has(id)) return;

        const item = cart.get(id);
        if (incId) {
          if (item.stock <= 0 || item.qty < item.stock) item.qty += 1;
        } else {
          item.qty -= 1;
          if (item.qty <= 0) cart.delete(id);
        }
        renderCart();
      });
    }

    if (checkoutButton) {
      checkoutButton.addEventListener("click", async () => {
        const items = Array.from(cart.values());
        if (!items.length || !whatsappNumber) return;

        clearOrderFeedback();
        const whatsappWindow = window.open("about:blank", "_blank");
        if (whatsappWindow) whatsappWindow.opener = null;
        checkoutButton.disabled = true;
        const order = await createCatalogOrder(items);
        checkoutButton.disabled = false;
        if (!order) {
          if (whatsappWindow) whatsappWindow.close();
          return;
        }

        const total = order.total || items.reduce((sum, item) => sum + item.qty * item.price, 0);
        const interestWord = inferInterestWord(order.customerName);
        const requesterName = order.customerName?.trim() || "Cliente";
        const lines = [
          `Hola, soy *${requesterName}* y estoy ${interestWord} en los siguientes productos:`,
          "",
          `Resumen de interes`,
          "",
          ...items.map((item, index) => {
            return [
              `${index + 1}. ${item.name}`,
              `   Cantidad: ${item.qty}`,
            ].join("\n");
          }),
          "",
          `Total estimado a cancelar: *${moneyLabel(total)}*`,
          "",
          `Quedo atento(a) a la informacion para continuar con la compra.`,
        ].filter(Boolean);
        const whatsappUrl = `https://wa.me/${whatsappNumber}?text=${encodeURIComponent(lines.join("\n"))}`;
        if (whatsappWindow) {
          whatsappWindow.location.href = whatsappUrl;
        } else {
          window.location.href = whatsappUrl;
        }
      });
    }

    [sellerQuoteButton, sellerInvoiceButton].forEach((button) => {
      if (!button) return;
      button.addEventListener("click", (event) => {
        if (button.getAttribute("aria-disabled") === "true") {
          event.preventDefault();
        }
      });
    });

    renderCart();
  }

  function initPrintButtons() {
    const buttons = Array.from(document.querySelectorAll("[data-print-document], [data-print-url]"));
    if (!buttons.length) return;

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const printUrl = button.getAttribute("data-print-url");
        if (printUrl) {
          const printWindow = window.open(printUrl, "_blank");
          if (!printWindow) return;
          printWindow.addEventListener("load", () => {
            printWindow.focus();
            printWindow.print();
          });
          return;
        }
        window.print();
      });
    });
  }

  function initFastNavigation() {
    const body = document.body;
    if (!body || body.dataset.navigationReady === "1") return;
    body.dataset.navigationReady = "1";

    let resetTimer = null;

    function resetNavigationState() {
      body.classList.remove("is-navigating");
      document.querySelectorAll(".nav-loading").forEach((node) => {
        node.classList.remove("nav-loading");
      });
      if (resetTimer) {
        window.clearTimeout(resetTimer);
        resetTimer = null;
      }
    }

    document.addEventListener(
      "click",
      (event) => {
        if (event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

        const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
        if (!(link instanceof HTMLAnchorElement)) return;

        const href = (link.getAttribute("href") || "").trim();
        if (!href || !href.startsWith("/") || href.startsWith("//")) return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        if (link.getAttribute("aria-disabled") === "true") return;

        body.classList.add("is-navigating");
        link.classList.add("nav-loading");
        resetTimer = window.setTimeout(resetNavigationState, 5000);
      },
      true,
    );

    window.addEventListener("pageshow", resetNavigationState);
    window.addEventListener("focus", resetNavigationState);
  }

  function initQuoteBuilder() {
    const form = document.querySelector('[data-page-form="quote"]');
    if (!form) return;

    const catalog = parseJsonScript("catalog-data");
    const clients = parseJsonScript("clients-data");
    const quoteItems = parseJsonScript("quote-items-data");
    const lineBody = document.getElementById("quote-lines");
    const rowTemplate = document.getElementById("quote-row-template");
    const addButton = document.getElementById("add-quote-line");
    const catalogSearchList = document.getElementById("catalog-search-options");
    const taxField = document.getElementById("quote-tax-rate");
    const marginField = document.getElementById("quote-price-margin");
    const marginPresetButtons = Array.from(document.querySelectorAll("[data-margin-preset]"));
    const roundingMode = form.dataset.roundingMode || "integer";
    const quoteLocation = document.getElementById("quote-location");
    const clientType = document.getElementById("client-type");
    const consumerFinal = document.getElementById("consumer-final");
    const clientRecordId = document.getElementById("client-record-id");
    const clientName = document.getElementById("client-name");
    const clientPhone = document.getElementById("client-phone");
    const clientAddress = document.getElementById("client-address");
    const clientDocumentType = document.getElementById("client-document-type");
    const clientDocumentNumber = document.getElementById("client-document-number");
    const clientEmail = document.getElementById("client-email");
    const clientTypeEditor = document.getElementById("client-type-editor");
    const clientNameEditor = document.getElementById("client-name-editor");
    const clientPhoneEditor = document.getElementById("client-phone-editor");
    const clientAddressEditor = document.getElementById("client-address-editor");
    const clientDocumentTypeEditor = document.getElementById("client-document-type-editor");
    const clientDocumentNumberEditor = document.getElementById("client-document-number-editor");
    const clientEmailEditor = document.getElementById("client-email-editor");
    const clientNameLabel = document.getElementById("client-name-label");
    const clientAddressLabel = document.getElementById("client-address-label");
    const clientBrowserToggle = document.getElementById("client-browser-toggle");
    const clientQuickCreate = document.getElementById("client-quick-create");
    const clientBrowserPanel = document.getElementById("client-browser-panel");
    const clientSearchQuery = document.getElementById("client-search-query");
    const clientSearchResults = document.getElementById("client-search-results");
    const clientSearchEmpty = document.getElementById("client-search-empty");
    const clientOptionalPanel = document.getElementById("client-optional-panel");
    const clientApplySelection = document.getElementById("client-apply-selection");
    const clientSaveQuick = document.getElementById("client-save-quick");
    const clientSaveFeedback = document.getElementById("client-save-feedback");
    const clientSelectedCard = document.getElementById("client-selected-card");
    const clientSelectedStatus = document.getElementById("client-selected-status");
    const clientSelectedEmpty = document.getElementById("client-selected-empty");
    const clientSelectedData = document.getElementById("client-selected-data");
    const clientSelectedName = document.getElementById("client-selected-name");
    const clientSelectedType = document.getElementById("client-selected-type");
    const clientSelectedPhone = document.getElementById("client-selected-phone");
    const clientSelectedAddress = document.getElementById("client-selected-address");
    const clientSelectedDocumentRow = document.getElementById("client-selected-document-row");
    const clientSelectedDocument = document.getElementById("client-selected-document");
    const clientSelectedEmailRow = document.getElementById("client-selected-email-row");
    const clientSelectedEmail = document.getElementById("client-selected-email");

    const catalogById = new Map(catalog.map((item) => [String(item.id), item]));
    const clientsById = new Map(clients.map((item) => [String(item.id), item]));

    function normalizeSearchValue(value) {
      return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .trim();
    }

    function defaultDocumentType(type) {
      if (type === "BUSINESS") return "NIT";
      if (type === "PERSONAL") return "CC";
      return "";
    }

    function clientTypeLabel(type) {
      if (type === "BUSINESS") return "Persona juridica / empresa";
      if (type === "PERSONAL") return "Persona natural";
      return "Cliente particular / consumidor final";
    }

    function currentClientSnapshot() {
      return {
        id: clientRecordId?.value || "",
        client_type: clientType?.value || "CONSUMER",
        name: clientName?.value || "",
        phone: clientPhone?.value || "",
        address: clientAddress?.value || "",
        document_type: clientDocumentType?.value || "",
        document_number: clientDocumentNumber?.value || "",
        email: clientEmail?.value || "",
      };
    }

    function syncEditorFromHidden() {
      if (clientTypeEditor) clientTypeEditor.value = clientType?.value || "CONSUMER";
      if (clientNameEditor) clientNameEditor.value = clientName?.value || "";
      if (clientPhoneEditor) clientPhoneEditor.value = clientPhone?.value || "";
      if (clientAddressEditor) clientAddressEditor.value = clientAddress?.value || "";
      if (clientDocumentTypeEditor) clientDocumentTypeEditor.value = clientDocumentType?.value || "";
      if (clientDocumentNumberEditor) clientDocumentNumberEditor.value = clientDocumentNumber?.value || "";
      if (clientEmailEditor) clientEmailEditor.value = clientEmail?.value || "";
    }

    function syncHiddenFromEditor() {
      const type = clientTypeEditor?.value || clientType?.value || "CONSUMER";
      const isConsumer = type === "CONSUMER";

      if (clientType) clientType.value = type;
      if (clientName) clientName.value = clientNameEditor?.value || "";
      if (clientPhone) clientPhone.value = clientPhoneEditor?.value || "";
      if (clientAddress) clientAddress.value = clientAddressEditor?.value || "";
      if (clientDocumentType) clientDocumentType.value = clientDocumentTypeEditor?.value || "";
      if (clientDocumentNumber) clientDocumentNumber.value = clientDocumentNumberEditor?.value || "";
      if (clientEmail) clientEmail.value = clientEmailEditor?.value || "";
      if (quoteLocation) quoteLocation.value = clientAddressEditor?.value || "";
      if (consumerFinal) consumerFinal.value = isConsumer ? "1" : "0";
    }

    function updateClientSummary() {
      const snapshot = currentClientSnapshot();
      const hasClient = Boolean(String(snapshot.name || "").trim());
      const documentValue = [snapshot.document_type, snapshot.document_number].filter(Boolean).join(" ");
      const emailValue = String(snapshot.email || "").trim();

      if (clientSelectedCard) clientSelectedCard.classList.toggle("is-empty", !hasClient);
      if (clientSelectedStatus) clientSelectedStatus.textContent = hasClient ? "Listo para cotizar" : "Sin cliente";
      if (clientSelectedEmpty) clientSelectedEmpty.classList.toggle("hidden", hasClient);
      if (clientSelectedData) clientSelectedData.classList.toggle("hidden", !hasClient);

      if (!hasClient) return;

      if (clientSelectedName) clientSelectedName.textContent = snapshot.name;
      if (clientSelectedType) clientSelectedType.textContent = clientTypeLabel(snapshot.client_type);
      if (clientSelectedPhone) clientSelectedPhone.textContent = snapshot.phone || "No registrado";
      if (clientSelectedAddress) clientSelectedAddress.textContent = snapshot.address || "Sin direccion registrada";
      if (clientSelectedDocumentRow) clientSelectedDocumentRow.classList.toggle("hidden", !documentValue);
      if (clientSelectedDocument) clientSelectedDocument.textContent = documentValue;
      if (clientSelectedEmailRow) clientSelectedEmailRow.classList.toggle("hidden", !emailValue);
      if (clientSelectedEmail) clientSelectedEmail.textContent = emailValue;
    }

    function setClientFields(client) {
      if (!client) return;
      if (clientRecordId) clientRecordId.value = client.id || "";
      if (clientType) clientType.value = client.client_type || "CONSUMER";
      if (clientName) clientName.value = client.name || "";
      if (clientDocumentType) clientDocumentType.value = client.document_type || "";
      if (clientDocumentNumber) clientDocumentNumber.value = client.document_number || "";
      if (clientEmail) clientEmail.value = client.email || "";
      if (clientPhone) clientPhone.value = client.phone || "";
      if (clientAddress) clientAddress.value = client.address || "";
      if (quoteLocation) quoteLocation.value = client.address || "";
      syncEditorFromHidden();
      syncClientMode();
      updateClientSummary();
      if (clientSaveFeedback) {
        clientSaveFeedback.textContent = `Cliente cargado: ${client.name || "Cliente"} (${clientTypeLabel(client.client_type)}).`;
      }
    }

    function clearClientFields() {
      if (clientRecordId) clientRecordId.value = "";
      if (clientType) clientType.value = "CONSUMER";
      if (clientName) clientName.value = "";
      if (clientPhone) clientPhone.value = "";
      if (clientAddress) clientAddress.value = "";
      if (clientDocumentType) clientDocumentType.value = "";
      if (clientDocumentNumber) clientDocumentNumber.value = "";
      if (clientEmail) clientEmail.value = "";
      if (quoteLocation) quoteLocation.value = "";
      syncEditorFromHidden();
      syncClientMode();
      updateClientSummary();
    }

    function syncClientMode() {
      const type = clientTypeEditor ? clientTypeEditor.value || "CONSUMER" : clientType ? clientType.value || "CONSUMER" : "CONSUMER";
      const isConsumer = type === "CONSUMER";

      if (clientType) clientType.value = type;
      if (consumerFinal) consumerFinal.value = isConsumer ? "1" : "0";

      if (clientNameLabel) {
        clientNameLabel.textContent =
          type === "BUSINESS" ? "Nombre de la empresa" : type === "PERSONAL" ? "Nombre completo" : "Nombre del cliente";
      }
      if (clientAddressLabel) {
        clientAddressLabel.textContent =
          type === "CONSUMER" ? "Ubicacion del cliente" : "Direccion o ubicacion del cliente";
      }

      if (clientOptionalPanel) clientOptionalPanel.classList.toggle("hidden", isConsumer);

      if (isConsumer) {
        if (clientDocumentType) clientDocumentType.value = "";
        if (clientDocumentNumber) clientDocumentNumber.value = "";
        if (clientEmail) clientEmail.value = "";
        if (clientDocumentTypeEditor) clientDocumentTypeEditor.value = "";
        if (clientDocumentNumberEditor) clientDocumentNumberEditor.value = "";
        if (clientEmailEditor) clientEmailEditor.value = "";
      } else if (clientDocumentType && !clientDocumentType.value && clientDocumentNumber?.value) {
        clientDocumentType.value = defaultDocumentType(type);
        if (clientDocumentTypeEditor) clientDocumentTypeEditor.value = clientDocumentType.value;
      }
    }

    function clientLabel(client) {
      return clientTypeLabel(client.client_type);
    }

    function renderClientResults(query) {
      if (!clientSearchResults) return;

      const needle = normalizeSearchValue(query);
      const filtered = clients.filter((client) => {
        if (!needle) return true;
        const haystack = normalizeSearchValue(
          [
            client.name,
            client.phone,
            client.address,
            client.document_type,
            client.document_number,
            client.email,
          ].join(" "),
        );
        return haystack.includes(needle);
      });

      clientSearchResults.innerHTML = "";

      filtered.slice(0, 12).forEach((client) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "quote-client-result";
        button.innerHTML = `
          <strong>${client.name || "Cliente"}</strong>
          <span>${clientLabel(client)}${client.phone ? ` · ${client.phone}` : ""}</span>
          <small>${client.address || "Sin direccion registrada"}</small>
        `;
        button.addEventListener("click", () => {
          setClientFields(client);
          if (clientBrowserPanel) clientBrowserPanel.classList.add("hidden");
        });
        clientSearchResults.appendChild(button);
      });

      if (clientSearchEmpty) clientSearchEmpty.classList.toggle("hidden", filtered.length > 0);
    }

    function currentMarginPercent() {
      return clampMarginPercent(marginField ? marginField.value : 100);
    }

    function syncMarginInputs(value) {
      const normalized = clampMarginPercent(value);
      if (marginField) marginField.value = formatMarginPercent(normalized);
      marginPresetButtons.forEach((button) => {
        const presetValue = clampMarginPercent(button.dataset.marginPreset);
        button.classList.toggle("active", Math.abs(presetValue - normalized) < 0.001);
      });
      return normalized;
    }

    function adjustedPriceFromMargin(basePrice) {
      const marginPercent = currentMarginPercent();
      const factor = marginPercent / 100;
      return roundValue(Number(basePrice || 0) / factor, roundingMode);
    }

    function basePriceFromAdjusted(price) {
      const marginPercent = currentMarginPercent();
      const factor = marginPercent / 100;
      return roundValue(Number(price || 0) * factor, roundingMode);
    }

    function catalogItemLabel(item) {
      if (!item) return "";
      return `${item.sku || "ITEM"} - ${item.description || "Sin descripcion"}`;
    }

    function catalogSearchValues(item) {
      if (!item) return [];
      return [item.sku || "", item.description || "", catalogItemLabel(item)].filter(Boolean);
    }

    function findCatalogItem(query) {
      const needle = normalizeSearchValue(query);
      if (!needle) return null;

      const exactMatch = catalog.find((item) =>
        catalogSearchValues(item).some((candidate) => normalizeSearchValue(candidate) === needle),
      );
      if (exactMatch) return exactMatch;

      return (
        catalog.find((item) =>
          catalogSearchValues(item).some((candidate) => normalizeSearchValue(candidate).includes(needle)),
        ) || null
      );
    }

    function renderCatalogSearchList(items = catalog) {
      if (!catalogSearchList) return;
      const seen = new Set();
      const fragment = document.createDocumentFragment();

      items.forEach((item) => {
        catalogSearchValues(item).forEach((candidate) => {
          const normalized = normalizeSearchValue(candidate);
          if (!normalized || seen.has(normalized)) return;
          seen.add(normalized);
          const option = document.createElement("option");
          option.value = candidate;
          fragment.appendChild(option);
        });
      });

      catalogSearchList.innerHTML = "";
      catalogSearchList.appendChild(fragment);
    }

    function applyCatalogItemToRow(row, item, query = "") {
      if (!row || !item) return;

      const searchField = row.querySelector(".catalog-search");
      const sourceItemId = row.querySelector('[name="source_item_id"]');
      const qty = row.querySelector('[name="qty"]');
      const cost = row.querySelector('[name="cost_amount"]');
      const basePrice = row.querySelector('[name="base_price_unit"]');
      const taxable = row.querySelector('[name="taxable"]');
      const sku = row.querySelector('[name="sku"]');
      const description = row.querySelector('[name="description"]');
      const unit = row.querySelector('[name="unit"]');

      if (sourceItemId) sourceItemId.value = String(item.id);
      if (searchField) searchField.value = query || catalogItemLabel(item);
      if (sku) sku.value = item.sku || "";
      if (description) description.value = item.description || "";
      if (unit) unit.value = item.unit || "";
      if (qty) qty.value = qty.value || 1;
      if (cost) cost.value = item.cost_amount || 0;
      if (basePrice) basePrice.value = item.suggested_price || 0;
      if (taxable) taxable.value = Number(item.taxable ?? 1) ? "1" : "0";
      applyMarginToRow(row);
      updateTotals();
    }

    function lineValues(row) {
      const qty = Number(row.querySelector('[name="qty"]').value || 0);
      const price = Number(row.querySelector('[name="price_unit"]').value || 0);
      const discountValue = Number(row.querySelector('[name="discount_value"]').value || 0);
      const discountType = row.querySelector('[name="discount_type"]').value;
      const taxable = row.querySelector('[name="taxable"]').value !== "0";
      const subtotal = qty * price;
      const discount = discountType === "VALUE" ? discountValue : subtotal * (discountValue / 100);
      const total = Math.max(subtotal - discount, 0);
      return {
        taxable,
        total: roundValue(total, roundingMode),
      };
    }

    function applyMarginToRow(row) {
      const basePrice = row.querySelector('[name="base_price_unit"]');
      const price = row.querySelector('[name="price_unit"]');
      price.value = adjustedPriceFromMargin(basePrice.value || 0);
    }

    function updateTotals() {
      let subtotal = 0;
      let taxableSubtotal = 0;
      lineBody.querySelectorAll(".quote-row").forEach((row) => {
        const values = lineValues(row);
        subtotal += values.total;
        if (values.taxable) {
          taxableSubtotal += values.total;
        }
        row.querySelector(".line-total-output").textContent = formatMoney(values.total, roundingMode);
      });

      subtotal = roundValue(subtotal, roundingMode);
      taxableSubtotal = roundValue(taxableSubtotal, roundingMode);
      const tax = roundValue(taxableSubtotal * (Number(taxField.value || 0) / 100), roundingMode);
      const total = roundValue(subtotal + tax, roundingMode);

      document.getElementById("subtotal-output").textContent = formatMoney(subtotal, roundingMode);
      document.getElementById("tax-output").textContent = formatMoney(tax, roundingMode);
      document.getElementById("grand-total-output").textContent = formatMoney(total, roundingMode);
    }

    function focusCatalogSearch(row) {
      const searchField = row?.querySelector(".catalog-search");
      if (!searchField) return;
      requestAnimationFrame(() => {
        searchField.focus();
        searchField.select();
      });
    }

    function bindRow(row) {
      const searchField = row.querySelector(".catalog-search");
      const sourceItemId = row.querySelector('[name="source_item_id"]');
      const qty = row.querySelector('[name="qty"]');
      const cost = row.querySelector('[name="cost_amount"]');
      const basePrice = row.querySelector('[name="base_price_unit"]');
      const price = row.querySelector('[name="price_unit"]');
      const taxable = row.querySelector('[name="taxable"]');
      const sku = row.querySelector('[name="sku"]');
      const description = row.querySelector('[name="description"]');
      const unit = row.querySelector('[name="unit"]');
      const discountType = row.querySelector('[name="discount_type"]');
      const discountValue = row.querySelector('[name="discount_value"]');
      const removeButton = row.querySelector(".remove-line");

      if (searchField) {
        const applyCatalogSearchMatch = () => {
          const query = String(searchField.value || "").trim();
          if (!query) {
            if (sourceItemId) sourceItemId.value = "";
            return false;
          }
          const item = findCatalogItem(query);
          if (!item) return false;
          applyCatalogItemToRow(row, item, query);
          return true;
        };

        searchField.addEventListener("change", () => {
          applyCatalogSearchMatch();
        });
        searchField.addEventListener("blur", () => {
          applyCatalogSearchMatch();
        });
        searchField.addEventListener("keydown", (event) => {
          if (event.key !== "Enter") return;
          if (!applyCatalogSearchMatch()) return;
          event.preventDefault();
          const nextRow = addRow();
          focusCatalogSearch(nextRow);
        });
      }

      [qty, cost, taxable, discountType, discountValue, sku, description, unit].forEach((field) => {
        if (!field) return;
        field.addEventListener("input", updateTotals);
        field.addEventListener("change", updateTotals);
      });

      price.addEventListener("input", () => {
        basePrice.value = basePriceFromAdjusted(price.value || 0);
        updateTotals();
      });
      price.addEventListener("change", () => {
        basePrice.value = basePriceFromAdjusted(price.value || 0);
        updateTotals();
      });

      removeButton.addEventListener("click", () => {
        row.remove();
        if (!lineBody.children.length) {
          addRow();
        }
        updateTotals();
      });
    }

    function addRow(seed) {
      const fragment = rowTemplate.content.cloneNode(true);
      lineBody.appendChild(fragment);

      const createdRow = lineBody.lastElementChild;
      bindRow(createdRow);

      if (seed) {
        createdRow.querySelector('[name="sku"]').value = seed.sku || "";
        createdRow.querySelector('[name="description"]').value = seed.description || "";
        createdRow.querySelector('[name="unit"]').value = seed.unit || "";
        createdRow.querySelector('[name="qty"]').value = seed.qty || 1;
        createdRow.querySelector('[name="cost_amount"]').value = seed.cost_amount || 0;
        createdRow.querySelector('[name="base_price_unit"]').value = seed.base_price_unit || seed.price_unit || 0;
        createdRow.querySelector('[name="price_unit"]').value = seed.price_unit || 0;
        createdRow.querySelector('[name="taxable"]').value = Number(seed.taxable ?? 1) ? "1" : "0";
        createdRow.querySelector('[name="discount_type"]').value = seed.discount_type || "PERCENT";
        createdRow.querySelector('[name="discount_value"]').value = seed.discount_value || 0;
        if (seed.source_item_id) {
          const seededItem = catalogById.get(String(seed.source_item_id));
          createdRow.querySelector('[name="source_item_id"]').value = String(seed.source_item_id);
          const searchField = createdRow.querySelector(".catalog-search");
          if (searchField && seededItem) {
            searchField.value = seededItem.description || catalogItemLabel(seededItem);
          }
        }
      } else {
        createdRow.querySelector('[name="base_price_unit"]').value = 0;
      }

      applyMarginToRow(createdRow);
      updateTotals();
      return createdRow;
    }

    if (addButton) {
      addButton.addEventListener("click", () => addRow());
    }
    if (taxField) {
      taxField.addEventListener("input", updateTotals);
      taxField.addEventListener("change", updateTotals);
    }
    if (marginField) {
      syncMarginInputs(marginField.value || 100);
      const handleMarginChange = (value) => {
        syncMarginInputs(value);
        lineBody.querySelectorAll(".quote-row").forEach((row) => applyMarginToRow(row));
        updateTotals();
      };
      marginField.addEventListener("input", () => handleMarginChange(marginField.value));
      marginField.addEventListener("change", () => handleMarginChange(marginField.value));
      marginPresetButtons.forEach((button) => {
        button.addEventListener("click", () => handleMarginChange(button.dataset.marginPreset));
      });
    }

    renderCatalogSearchList();

    if (clientType) {
      syncEditorFromHidden();

      const syncClientEdition = () => {
        syncHiddenFromEditor();
        if (!clientDocumentType?.value && clientDocumentNumber?.value) {
          clientDocumentType.value = defaultDocumentType(clientType.value);
          if (clientDocumentTypeEditor) clientDocumentTypeEditor.value = clientDocumentType.value;
        }
        syncClientMode();
        updateClientSummary();
      };

      if (clientTypeEditor) {
        clientTypeEditor.addEventListener("change", syncClientEdition);
      }

      [clientNameEditor, clientPhoneEditor, clientAddressEditor, clientDocumentTypeEditor, clientDocumentNumberEditor, clientEmailEditor].forEach((field) => {
        if (!field) return;
        field.addEventListener("input", syncClientEdition);
        field.addEventListener("change", syncClientEdition);
      });

      syncClientMode();
      updateClientSummary();
    }

    if (clientBrowserToggle && clientBrowserPanel) {
      clientBrowserToggle.addEventListener("click", () => {
        clientBrowserPanel.classList.toggle("hidden");
        renderClientResults(clientSearchQuery ? clientSearchQuery.value : "");
        if (!clientBrowserPanel.classList.contains("hidden") && clientSearchQuery) {
          clientSearchQuery.focus();
        }
      });
    }

    if (clientSearchQuery) {
      clientSearchQuery.addEventListener("input", () => {
        renderClientResults(clientSearchQuery.value);
      });
      renderClientResults(clientSearchQuery.value);
    } else {
      renderClientResults("");
    }

    if (clientQuickCreate) {
      clientQuickCreate.addEventListener("click", () => {
        clearClientFields();
        if (clientBrowserPanel) clientBrowserPanel.classList.remove("hidden");
        if (clientNameEditor) clientNameEditor.focus();
        if (clientSaveFeedback) {
          clientSaveFeedback.textContent = "Escribe nombre, telefono y ubicacion. Si quieres reutilizarlo despues, guardalo en la base.";
        }
      });
    }

    if (clientApplySelection) {
      clientApplySelection.addEventListener("click", () => {
        syncHiddenFromEditor();
        syncClientMode();
        updateClientSummary();
        if (clientBrowserPanel) clientBrowserPanel.classList.add("hidden");
        if (clientSaveFeedback) {
          clientSaveFeedback.textContent = clientName?.value
            ? `Cliente aplicado a la cotizacion: ${clientName.value}.`
            : "Completa al menos nombre, telefono y ubicacion para continuar.";
        }
      });
    }

    if (clientSaveQuick) {
      clientSaveQuick.addEventListener("click", async () => {
        syncHiddenFromEditor();

        if (!clientName?.value || !clientPhone?.value || !clientAddress?.value) {
          if (clientSaveFeedback) {
            clientSaveFeedback.textContent = "Para guardar el cliente necesitas nombre, telefono y ubicacion.";
          }
          return;
        }

        const payload = new FormData();
        payload.set("id", clientRecordId?.value || "");
        payload.set("client_type", clientType?.value || "CONSUMER");
        payload.set("name", clientName?.value || "");
        payload.set("phone", clientPhone?.value || "");
        payload.set("address", clientAddress?.value || "");
        payload.set("document_type", clientDocumentType?.value || "");
        payload.set("document_number", clientDocumentNumber?.value || "");
        payload.set("email", clientEmail?.value || "");

        if (clientSaveFeedback) {
          clientSaveFeedback.textContent = "Guardando cliente...";
        }

        try {
          const response = await fetch("/api/clients/quick-save", {
            method: "POST",
            body: payload,
          });
          const result = await response.json();
          if (!response.ok || !result.ok) {
            throw new Error(result.error || "No se pudo guardar el cliente.");
          }

          const client = result.client;
          clientsById.set(String(client.id), client);
          const existingIndex = clients.findIndex((item) => String(item.id) === String(client.id));
          if (existingIndex >= 0) {
            clients[existingIndex] = client;
          } else {
            clients.push(client);
          }
          setClientFields(client);
          renderClientResults(clientSearchQuery ? clientSearchQuery.value : "");
          if (clientSaveFeedback) {
            clientSaveFeedback.textContent = `Cliente guardado correctamente: ${client.name}.`;
          }
        } catch (error) {
          if (clientSaveFeedback) {
            clientSaveFeedback.textContent = error.message || "No se pudo guardar el cliente.";
          }
        }
      });
    }

    if (quoteItems.length) {
      quoteItems.forEach((item) => addRow(item));
    } else {
      addRow();
    }

    if (!clientName?.value && clientType?.value === "CONSUMER" && clientSaveFeedback) {
      clientSaveFeedback.textContent = "Para cliente particular solo necesitas nombre, ubicacion y telefono.";
    }
  }

  function initApp() {
    initFastNavigation();

    if (document.querySelector('[data-page-form="catalog"]')) {
      initCatalogForm();
    }

    if (document.querySelector('[data-page-form="quote"]')) {
      initQuoteBuilder();
    }

    if (document.querySelector("[data-copy-text]")) {
      initCopyButtons();
    }

    if (document.querySelector("[data-cart-panel]")) {
      initSharedCatalogCart();
    }

    if (document.querySelector("[data-print-document], [data-print-url]")) {
      initPrintButtons();
    }

    if (document.querySelector("[data-video-toggle]")) {
      onIdle(initVideoPlayers);
    }

    if (document.querySelector("[data-gallery]")) {
      onIdle(initCatalogGalleries);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp, { once: true });
  } else {
    initApp();
  }
})();
