// Live clock: starts from the SERVER time (sent in data-epoch) and ticks every second.
(function () {
  var el = document.getElementById("clock");
  if (!el) return;
  var offset = Number(el.dataset.epoch) - Date.now();
  var fmt = new Intl.DateTimeFormat("en-IN", {
    weekday: "short", day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true, timeZone: "Asia/Kolkata"
  });
  function tick() { el.textContent = fmt.format(new Date(Date.now() + offset)) + " IST"; }
  tick();
  setInterval(tick, 1000);
})();
