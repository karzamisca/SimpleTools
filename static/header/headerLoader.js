// static/header/headerLoader.js
(function () {
  "use strict";

  // Configuration
  const CONFIG = {
    headerPath: "/static/header/header.html",
    insertPosition: "afterbegin",
    containerSelector: "body",
    activeClass: "active",
    version: "1.0",
  };

  // Styles
  const styles = `
    <style id="header-component-styles">
      .app-header {
        background: #fff;
        border-bottom: 1px solid #e0e0e0;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 1000;
        width: 100%;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
      }

      .header-nav {
        max-width: 1200px;
        margin: 0 auto;
        padding: 0 20px;
      }

      .nav-container {
        display: flex;
        align-items: center;
        justify-content: space-between;
        height: 64px;
      }

      .nav-brand {
        font-size: 18px;
        font-weight: 500;
        color: #111;
        letter-spacing: -0.3px;
      }

      .nav-links {
        display: flex;
        list-style: none;
        margin: 0;
        padding: 0;
        gap: 32px;
      }

      .nav-link {
        text-decoration: none;
        color: #444;
        font-size: 15px;
        font-weight: 400;
        padding: 8px 0;
        transition: all 0.15s ease;
        border-bottom: 2px solid transparent;
      }

      .nav-link:hover {
        color: #111;
        border-bottom-color: #ccc;
      }

      .nav-link.active {
        color: #111;
        border-bottom-color: #111;
        font-weight: 500;
      }

      /* Ensure content doesn't hide behind fixed header */
      body {
        padding-top: 64px !important;
        margin: 0;
      }

      /* Mobile responsive */
      @media (max-width: 600px) {
        .nav-container {
          flex-direction: column;
          height: auto;
          padding: 16px 0;
          gap: 12px;
        }

        .nav-links {
          gap: 24px;
        }
        
        body {
          padding-top: 100px !important;
        }
      }
    </style>
  `;

  // Load header function
  async function loadHeader() {
    try {
      // Fetch header HTML
      const response = await fetch(`${CONFIG.headerPath}?v=${CONFIG.version}`);

      if (!response.ok) {
        throw new Error(`Failed to load header: ${response.status}`);
      }

      const headerHTML = await response.text();

      // Inject styles if not already present
      if (!document.getElementById("header-component-styles")) {
        document.head.insertAdjacentHTML("beforeend", styles);
      }

      // Insert header
      const container = document.querySelector(CONFIG.containerSelector);
      container.insertAdjacentHTML(CONFIG.insertPosition, headerHTML);

      // Highlight active link
      highlightActiveLink();

      console.log("✅ Header component loaded v" + CONFIG.version);
    } catch (error) {
      console.error("❌ Error loading header:", error);
      createFallbackHeader();
    }
  }

  // Highlight current page link
  function highlightActiveLink() {
    const currentPath = window.location.pathname;
    const links = document.querySelectorAll(".nav-link");

    links.forEach((link) => {
      const href = link.getAttribute("href");

      // Check if current path matches
      if (
        currentPath === href ||
        (href !== "/" && currentPath.startsWith(href))
      ) {
        link.classList.add(CONFIG.activeClass);
      }

      // Special case for root
      if (currentPath === "/" && href === "/transcription") {
        link.classList.add(CONFIG.activeClass);
      }
    });
  }

  // Fallback header in case of error
  function createFallbackHeader() {
    const fallback = document.createElement("div");
    fallback.style.cssText = `
      padding: 15px 20px;
      background: #fff;
      border-bottom: 1px solid #e0e0e0;
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 1000;
    `;
    fallback.innerHTML = `
      <div style="max-width: 1200px; margin: 0 auto; display: flex; gap: 30px;">
        <a href="/" style="color: #111; text-decoration: none;">📝 Phiên Âm</a>
        <a href="/scraperZLibrary" style="color: #111; text-decoration: none;">📚 Z-Library Scraper</a>
      </div>
    `;
    document.body.insertAdjacentElement("afterbegin", fallback);
    document.body.style.paddingTop = "50px";
  }

  // Initialize when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadHeader);
  } else {
    loadHeader();
  }
})();
