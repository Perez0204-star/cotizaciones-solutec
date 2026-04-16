(function () {
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

  function initQuoteBuilder() {
    const form = document.querySelector('[data-page-form="quote"]');
    if (!form) return;

    const catalog = parseJsonScript("catalog-data");
    const clients = parseJsonScript("clients-data");
    const quoteItems = parseJsonScript("quote-items-data");
    const lineBody = document.getElementById("quote-lines");
    const rowTemplate = document.getElementById("quote-row-template");
    const addButton = document.getElementById("add-quote-line");
    const taxField = document.getElementById("quote-tax-rate");
    const marginField = document.getElementById("quote-price-margin");
    const marginPresetButtons = Array.from(document.querySelectorAll("[data-margin-preset]"));
    const roundingMode = form.dataset.roundingMode || "integer";
    const clientSelect = document.getElementById("client-select");
    const clientName = document.getElementById("client-name");
    const clientEmail = document.getElementById("client-email");

    const catalogById = new Map(catalog.map((item) => [String(item.id), item]));
    const clientsById = new Map(clients.map((item) => [String(item.id), item]));

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

    function optionMarkup() {
      const fragment = document.createDocumentFragment();
      const manualOption = document.createElement("option");
      manualOption.value = "";
      manualOption.textContent = "Manual";
      fragment.appendChild(manualOption);

      catalog.forEach((item) => {
        const option = document.createElement("option");
        option.value = String(item.id);
        option.textContent = `${item.sku} - ${item.description}`;
        fragment.appendChild(option);
      });
      return fragment;
    }

    function lineValues(row) {
      const qty = Number(row.querySelector('[name="qty"]').value || 0);
      const price = Number(row.querySelector('[name="price_unit"]').value || 0);
      const discountValue = Number(row.querySelector('[name="discount_value"]').value || 0);
      const discountType = row.querySelector('[name="discount_type"]').value;
      const subtotal = qty * price;
      const discount = discountType === "VALUE" ? discountValue : subtotal * (discountValue / 100);
      const total = Math.max(subtotal - discount, 0);
      return {
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
      lineBody.querySelectorAll(".quote-row").forEach((row) => {
        const values = lineValues(row);
        subtotal += values.total;
        row.querySelector(".line-total-output").textContent = formatMoney(values.total, roundingMode);
      });

      subtotal = roundValue(subtotal, roundingMode);
      const tax = roundValue(subtotal * (Number(taxField.value || 0) / 100), roundingMode);
      const total = roundValue(subtotal + tax, roundingMode);

      document.getElementById("subtotal-output").textContent = formatMoney(subtotal, roundingMode);
      document.getElementById("tax-output").textContent = formatMoney(tax, roundingMode);
      document.getElementById("grand-total-output").textContent = formatMoney(total, roundingMode);
    }

    function bindRow(row) {
      const select = row.querySelector(".catalog-select");
      const qty = row.querySelector('[name="qty"]');
      const cost = row.querySelector('[name="cost_amount"]');
      const basePrice = row.querySelector('[name="base_price_unit"]');
      const price = row.querySelector('[name="price_unit"]');
      const sku = row.querySelector('[name="sku"]');
      const description = row.querySelector('[name="description"]');
      const unit = row.querySelector('[name="unit"]');
      const discountType = row.querySelector('[name="discount_type"]');
      const discountValue = row.querySelector('[name="discount_value"]');
      const removeButton = row.querySelector(".remove-line");

      select.addEventListener("change", () => {
        const item = catalogById.get(select.value);
        if (!item) {
          updateTotals();
          return;
        }
        sku.value = item.sku || "";
        description.value = item.description || "";
        unit.value = item.unit || "";
        qty.value = qty.value || 1;
        cost.value = item.cost_amount || 0;
        basePrice.value = item.suggested_price || 0;
        applyMarginToRow(row);
        updateTotals();
      });

      [qty, cost, discountType, discountValue, sku, description, unit].forEach((field) => {
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
      const row = fragment.querySelector(".quote-row");
      const select = row.querySelector(".catalog-select");
      select.appendChild(optionMarkup());
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
        createdRow.querySelector('[name="discount_type"]').value = seed.discount_type || "PERCENT";
        createdRow.querySelector('[name="discount_value"]').value = seed.discount_value || 0;
        if (seed.source_item_id) {
          createdRow.querySelector(".catalog-select").value = String(seed.source_item_id);
        }
      } else {
        createdRow.querySelector('[name="base_price_unit"]').value = 0;
      }

      applyMarginToRow(createdRow);
      updateTotals();
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

    if (clientSelect && clientName && clientEmail) {
      clientSelect.addEventListener("change", () => {
        const client = clientsById.get(clientSelect.value);
        if (!client) return;
        clientName.value = client.name || "";
        clientEmail.value = client.email || "";
      });
    }

    if (quoteItems.length) {
      quoteItems.forEach((item) => addRow(item));
    } else {
      addRow();
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCatalogForm();
    initQuoteBuilder();
  });
})();
