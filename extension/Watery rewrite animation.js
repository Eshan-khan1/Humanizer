// Injects the SVG ripple filter once per page; safe to call repeatedly
function ensureHumanizerRippleFilter() {
    if (document.getElementById('humanizer-ripple-filter')) return;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.style.position = 'absolute';
    svg.style.overflow = 'hidden';
    svg.innerHTML =
      '<filter id="humanizer-ripple-filter" x="-20%" y="-20%" width="140%" height="140%">' +
        '<feTurbulence type="fractalNoise" baseFrequency="0.015 0.05" numOctaves="2" seed="6" result="humanizer-noise">' +
          '<animate attributeName="baseFrequency" dur="4s" values="0.015 0.05;0.025 0.06;0.015 0.05" repeatCount="indefinite" />' +
        '</feTurbulence>' +
        '<feDisplacementMap in="SourceGraphic" in2="humanizer-noise" scale="7" xChannelSelector="R" yChannelSelector="G" />' +
      '</filter>';
    document.body.appendChild(svg);
  }
  
  // Call when the rewrite request is sent, passing the selected text element
  function startWateryEffect(el) {
    ensureHumanizerRippleFilter();
    el.classList.remove('humanizer-watery-settle');
    el.classList.add('humanizer-watery');
  }
  
  // Call when the rewrite response arrives, passing the same element and the new text
  function resolveWateryEffect(el, newText) {
    el.classList.remove('humanizer-watery');
    el.textContent = newText;
    el.classList.add('humanizer-watery-settle');
  }