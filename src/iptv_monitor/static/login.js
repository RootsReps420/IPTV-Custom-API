/* Sign-in front page: POST /login, then go where the server says.
 * ?next=<path> is passed through and checked server-side (same-site, allowed for the role).
 */
(() => {
  const form = document.getElementById("login-form");
  const user = document.getElementById("login-user");
  const pass = document.getElementById("login-pass");
  const remember = document.getElementById("login-remember");
  const error = document.getElementById("login-error");
  const button = document.getElementById("login-btn");
  const toggle = document.getElementById("pw-toggle");
  const next = new URLSearchParams(location.search).get("next") || "/";

  function showError(text) {
    error.textContent = text;
    error.hidden = !text;
  }

  toggle.addEventListener("click", () => {
    const show = pass.type === "password";
    pass.type = show ? "text" : "password";
    toggle.textContent = show ? "Hide" : "Show";
    toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
    pass.focus();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!user.value.trim() || !pass.value) {
      showError("Enter your username and password.");
      return;
    }
    showError("");
    button.disabled = true;
    button.classList.add("busy");
    try {
      const response = await fetch("/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: user.value.trim(),
          password: pass.value,
          remember: remember.checked,
          next,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const fallback = response.status === 429 ? "Too many attempts. Try again in a few minutes." : "Sign-in failed.";
        showError(typeof data.detail === "string" ? data.detail : fallback);
        pass.select();
        return;
      }
      button.classList.add("ok");
      location.replace(data.next || "/");
    } catch {
      showError("Can't reach the server. Check your connection and try again.");
    } finally {
      button.disabled = false;
      button.classList.remove("busy");
    }
  });

  user.focus();
})();
