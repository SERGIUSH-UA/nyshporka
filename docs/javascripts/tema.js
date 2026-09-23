// Перемкнули тему в документації — та сама тема й на порталі.
//
// Портал і документація живуть на одному домені (nyshporka.online і
// nyshporka.online/docs/), тож бачать той самий localStorage. Material
// тримає вибір у своєму `__palette`; тут він дублюється в ключ порталу.
// Прямий бік (портал → документація) — інлайном у overrides/main.html,
// бо мусить спрацювати до першого малювання.
(function () {
  "use strict";
  document.addEventListener("change", function (e) {
    var input = e.target;
    if (!input || input.name !== "__palette") return;
    try {
      localStorage.setItem(
        "supriaha-tema",
        input.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "light"
      );
    } catch (err) {
      // Приватне вікно: тема лишається до перезавантаження, і це нормально.
    }
  });
})();
