// Init script: Playwright wstrzykuje go do każdego dokumentu PRZED pierwszym skryptem strony.
// Dzięki temu dataLayer, który zastanie strona, jest już naszą tablicą z podsłuchanym push.
// Strona robi `window.dataLayer = window.dataLayer || []`, więc przejmuje nasz obiekt.
(() => {
  const log = [];
  const MARK = '__dataLayerAudit';

  // gtag() robi dataLayer.push(arguments). `arguments` to obiekt tablicopodobny, a nie
  // tablica: JSON.stringify zrobiłby z niego {"0":"consent","1":"default",...} i kontrakt
  // nie rozpoznałby komendy. Array.from zamienia go na prawdziwą tablicę.
  const isArguments = (v) => Object.prototype.toString.call(v) === '[object Arguments]';

  // Snapshot w momencie pusha, a nie referencja: strona może później zmutować obiekt
  // i wtedy audyt widziałby stan z chwili odczytu, nie z chwili wysłania.
  // Funkcji i undefined JSON nie przenosi - zamieniamy je na znaczniki, żeby kontrakt
  // je zobaczył (np. eventCallback dostanie extra_forbidden), zamiast cicho zgubić.
  const snapshot = (v) =>
    JSON.parse(
      JSON.stringify(isArguments(v) ? Array.from(v) : v, (_key, x) => {
        if (typeof x === 'function') return '[function]';
        if (x === undefined) return '[undefined]';
        return x;
      }),
    );

  const dl = (window.dataLayer = window.dataLayer || []);
  const nativePush = dl.push;
  const hookedPush = function (...items) {
    for (const item of items) {
      try {
        log.push({ t: performance.now(), payload: snapshot(item) });
      } catch (e) {
        log.push({ t: performance.now(), payload: '[unserializable]', error: String(e) });
      }
    }
    // Oryginalny push dalej działa - strona i (w etapie 6) GTM nie widzą różnicy.
    return nativePush.apply(this, items);
  };
  hookedPush[MARK] = true;
  dl.push = hookedPush;

  // Odczyt z Pythona. `hooked` wykrywa stronę, która nadpisała window.dataLayer nową
  // tablicą - wtedy dalsze pushe omijają podsłuch i audyt byłby fałszywie zielony.
  Object.defineProperty(window, MARK, {
    value: {
      read: () => ({ hooked: window.dataLayer?.push?.[MARK] === true, log }),
    },
  });
})();
