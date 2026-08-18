// Earnings Radar — drop-in sign in / sign up popup.
// Include on any page with:  <script type="module" src="assets/auth.js"></script>
// Triggers: an element with id="authTrigger", or any element with [data-auth-open].
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth, onAuthStateChanged, createUserWithEmailAndPassword, signInWithEmailAndPassword,
  signOut, updateProfile, GoogleAuthProvider, signInWithPopup, sendPasswordResetEmail,
  sendEmailVerification, EmailAuthProvider, reauthenticateWithCredential,
  reauthenticateWithPopup, deleteUser
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import { getFirestore, doc, getDoc, setDoc, deleteDoc, serverTimestamp, increment, arrayUnion, arrayRemove }
  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

// Same Firebase project as the iOS app.
// NOTE: add your Web app's appId from Firebase Console → Project settings → Your apps → Web.
// Email/password works without it.
const firebaseConfig = {
  apiKey: "AIzaSyCkYi_67SreyN6FG7oxrHLypOP0eOC3Efs",
  authDomain: "earnings-radar-f398e.firebaseapp.com",
  projectId: "earnings-radar-f398e",
  appId: "1:621874989792:web:348614b693e5d261b45e85"
};
const _fbApp = initializeApp(firebaseConfig);
const auth = getAuth(_fbApp);
const _fs = getFirestore(_fbApp);

/* ---------- Watchlist (window.erWatch) ----------
   Works signed-out via localStorage; signed-in it syncs to /users/{uid}.watchlist in Firestore.
   On sign-in the local and remote lists MERGE (union) so nothing a visitor starred is lost. */
let _wl = new Set();
try { _wl = new Set(JSON.parse(localStorage.getItem("er_watchlist") || "[]")); } catch (e) {}
const _wlCbs = [];
function _wlSave() {
  try { localStorage.setItem("er_watchlist", JSON.stringify([..._wl])); } catch (e) {}
  _wlCbs.forEach((f) => { try { f([..._wl]); } catch (e) {} });
}
window.erWatch = {
  list: () => [..._wl],
  has: (s) => _wl.has(String(s || "").toUpperCase()),
  signedIn: () => !!auth.currentUser,
  promptSignIn: () => { const t = document.getElementById("authTrigger"); if (t) t.click(); },
  toggle(s) {
    s = String(s || "").toUpperCase(); if (!s) return false;
    const on = !_wl.has(s); if (on) _wl.add(s); else _wl.delete(s);
    _wlSave();
    const u = auth.currentUser;
    if (u) setDoc(doc(_fs, "users", u.uid),
      { watchlist: on ? arrayUnion(s) : arrayRemove(s) }, { merge: true }).catch(() => {});
    return on;
  },
  onChange(f) { _wlCbs.push(f); },
};
async function _wlSync(user) {
  try {
    const snap = await getDoc(doc(_fs, "users", user.uid));
    const remote = (snap.exists() && Array.isArray(snap.data().watchlist)) ? snap.data().watchlist : [];
    const localOnly = [..._wl].filter((s) => !remote.includes(s));
    remote.forEach((s) => _wl.add(String(s).toUpperCase()));
    if (localOnly.length)
      await setDoc(doc(_fs, "users", user.uid), { watchlist: arrayUnion(...localOnly) }, { merge: true });
    _wlSave();
  } catch (e) { /* offline: local list still works */ }
}

/* Mirror each signed-in user into Firestore /users/{uid} — gives us our own browsable/exportable
   account list (email, name, provider, signup date, last seen). Rules allow each user to write
   only their own doc; no public reads. Best-effort: a Firestore hiccup must never break auth. */
function _mirrorUser(user) {
  try {
    setDoc(doc(_fs, "users", user.uid), {
      email: user.email || null,
      name: user.displayName || null,
      provider: (user.providerData[0] || {}).providerId || null,
      createdAt: user.metadata && user.metadata.creationTime || null,
      // Same signup moment as a real Timestamp: the console renders it in local time with the
      // hour/minute (createdAt above is a GMT *string*, which is unreadable at a glance).
      createdAtTs: (user.metadata && user.metadata.creationTime)
        ? new Date(user.metadata.creationTime) : null,
      lastSeen: serverTimestamp(),
      visits: increment(1)
    }, { merge: true }).catch(() => {});
  } catch (e) {}
}

/* Per-account time-on-site. Counts seconds only while the tab is VISIBLE, accumulates locally,
   and flushes to the user's doc as an increment every 2 min + whenever the tab is hidden/closed.
   Keeps Firestore writes tiny (~1/2min per active signed-in user) and never blocks the page. */
let _tActive = null, _tAccum = 0;
function _tStart() { if (_tActive == null && !document.hidden) _tActive = Date.now(); }
function _tPause() { if (_tActive != null) { _tAccum += (Date.now() - _tActive) / 1000; _tActive = null; } }
function _tFlush() {
  _tPause(); _tStart();
  const s = Math.round(_tAccum);
  if (!auth.currentUser || s < 5) return;
  _tAccum = 0;
  try {
    setDoc(doc(_fs, "users", auth.currentUser.uid),
      { totalSeconds: increment(s), lastSeen: serverTimestamp() }, { merge: true }).catch(() => {});
  } catch (e) {}
}
document.addEventListener("visibilitychange", () => { if (document.hidden) { _tFlush(); } else { _tStart(); } });
window.addEventListener("pagehide", _tFlush);
setInterval(_tFlush, 120000);
_tStart();

/* ---------- styles (scoped, self-contained) ---------- */
const css = `
.erAuth{position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;padding:18px;
  background:rgba(4,6,15,.72);backdrop-filter:blur(5px)}
.erAuth.on{display:flex}
.erAuth *{box-sizing:border-box}
.erAuth .box{width:100%;max-width:400px;background:#0d1430;border:1px solid rgba(255,255,255,.12);border-radius:20px;
  padding:24px;color:#ECECF1;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  box-shadow:0 30px 80px rgba(0,0,0,.6)}
.erAuth h3{font-size:22px;font-weight:900;letter-spacing:-.4px;margin:0}
.erAuth .close{position:absolute;top:14px;right:16px;width:32px;height:32px;border-radius:9px;border:1px solid rgba(255,255,255,.12);
  background:rgba(255,255,255,.05);color:#ECECF1;font-size:15px;cursor:pointer}
.erAuth .tabs{display:flex;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:4px;margin:16px 0}
.erAuth .tabs button{flex:1;padding:10px;border:0;background:none;color:#9AA4C2;font-weight:800;font-size:14px;border-radius:9px;cursor:pointer}
.erAuth .tabs button.active{background:rgba(255,255,255,.08);color:#ECECF1}
.erAuth label{font-size:11.5px;font-weight:800;letter-spacing:.4px;color:#9AA4C2;text-transform:uppercase;display:block;margin:0 0 5px}
.erAuth input{width:100%;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:11px;
  padding:12px 13px;color:#ECECF1;font-size:15px;outline:none;margin-bottom:12px}
.erAuth input:focus{border-color:#2F6BFF}
.erAuth .primary{width:100%;padding:13px;border:0;border-radius:12px;font-weight:800;font-size:15px;color:#fff;cursor:pointer;
  background:linear-gradient(135deg,#2F6BFF,#1547C4);box-shadow:0 8px 22px rgba(47,107,255,.4)}
.erAuth .primary:disabled{opacity:.6}
.erAuth .gbtn{width:100%;display:flex;align-items:center;justify-content:center;gap:10px;padding:11px;border:0;border-radius:12px;
  background:#fff;color:#1f2430;font-weight:800;font-size:15px;cursor:pointer;margin-top:2px}
.erAuth .divider{display:flex;align-items:center;gap:12px;color:#9AA4C2;font-size:12px;margin:14px 0}
.erAuth .divider::before,.erAuth .divider::after{content:"";flex:1;height:1px;background:rgba(255,255,255,.1)}
.erAuth .msg{font-size:13px;font-weight:700;min-height:18px;margin-top:10px}
.erAuth .msg.err{color:#F87171}.erAuth .msg.ok{color:#34D399}
.erAuth .forgot{color:#6BA5FF;font-weight:700;font-size:12.5px;cursor:pointer;display:inline-block;margin-top:10px}
.erAuth .foothint{color:#9AA4C2;font-size:12px;text-align:center;margin-top:14px}
.erAuth .acct{text-align:center}
.erAuth .av{width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#2F6BFF,#1547C4);display:flex;align-items:center;
  justify-content:center;font-size:24px;font-weight:900;color:#fff;margin:6px auto 12px}
.erAuth .acct .em{color:#9AA4C2;font-size:14px;margin-top:2px}
.erAuth .acct .row{display:grid;gap:10px;margin-top:20px}
.erAuth .ghost{width:100%;padding:12px;border:1px solid rgba(255,255,255,.12);border-radius:12px;background:rgba(255,255,255,.05);
  color:#ECECF1;font-weight:800;font-size:15px;cursor:pointer}
.erAuth .vnote{margin:14px 0 4px;padding:12px 14px;border:1px solid rgba(251,191,36,.35);background:rgba(251,191,36,.08);
  border-radius:12px;font-size:13px;color:#ECECF1;text-align:left;line-height:1.5}
.erAuth .vnote b{color:#FBBF24}
.erAuth .vrow{display:flex;gap:8px;margin-top:9px}
.erAuth .vrow button{flex:1;padding:8px;border:1px solid rgba(255,255,255,.14);border-radius:9px;background:rgba(255,255,255,.06);
  color:#ECECF1;font-weight:800;font-size:12.5px;cursor:pointer}
.erAuth .vrow button:hover{border-color:#FBBF24}
.erAuth .vmsg{font-size:12px;font-weight:700;color:#34D399;min-height:14px;margin-top:6px}
.erAuth .pwwrap{position:relative}
.erAuth .pwwrap input{padding-right:66px}
.erAuth .pwtoggle{position:absolute;right:7px;top:7px;bottom:19px;padding:0 11px;border:1px solid rgba(255,255,255,.12);
  border-radius:8px;background:rgba(255,255,255,.06);color:#9AA4C2;font-weight:800;font-size:11.5px;cursor:pointer;letter-spacing:.4px}
.erAuth .pwtoggle:hover{color:#ECECF1;border-color:#2F6BFF}
.erAuth .dellink{background:none;border:none;color:#F87171;opacity:.75;font-weight:700;font-size:12.5px;cursor:pointer;margin-top:16px;text-decoration:underline}
.erAuth .dellink:hover{opacity:1}
.erAuth .delbox{margin-top:14px;padding:14px;border:1px solid rgba(248,113,113,.4);background:rgba(248,113,113,.07);border-radius:12px;font-size:13px;text-align:left;line-height:1.5}
.erAuth .delbox b{color:#F87171}
.erAuth .delbox p{color:#9AA4C2;font-size:12.5px;margin:6px 0 10px}
.erAuth .delbox input{margin-bottom:0}
.erAuth .delconfirm{background:linear-gradient(135deg,#F87171,#DC2626)!important;border:none!important;color:#fff!important}`;
const style = document.createElement("style"); style.textContent = css; document.head.appendChild(style);

/* ---------- markup ---------- */
const root = document.createElement("div");
root.className = "erAuth";
root.innerHTML = `
  <div class="box" style="position:relative">
    <button class="close" data-close aria-label="Close">✕</button>

    <div data-view="form">
      <h3 data-title>Welcome back</h3>
      <div class="tabs">
        <button data-tab="signin" class="active" type="button">Sign in</button>
        <button data-tab="signup" type="button">Create account</button>
      </div>
      <form data-form>
        <div data-namewrap style="display:none">
          <label>Name</label>
          <input type="text" data-name autocomplete="name" placeholder="Alex Rivera" />
        </div>
        <label>Email</label>
        <input type="email" data-email autocomplete="email" placeholder="you@example.com" required />
        <label>Password</label>
        <div class="pwwrap">
          <input type="password" data-password autocomplete="current-password" placeholder="••••••••" required />
          <button type="button" class="pwtoggle" data-pwtoggle aria-label="Show password">Show</button>
        </div>
        <button class="primary" type="submit" data-submit>Sign in</button>
        <div class="msg" data-msg></div>
        <span class="forgot" data-forgot>Forgot password?</span>
      </form>
      <div class="divider">or</div>
      <button class="gbtn" data-google type="button">
        <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.1 0 24 0 14.6 0 6.4 5.4 2.5 13.3l7.8 6.1C12.2 13.2 17.6 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-2.8-.4-4.1H24v7.8h12.4c-.3 2.1-1.6 5.2-4.6 7.3l7.1 5.5c4.3-3.9 6.8-9.7 6.8-16.5z"/><path fill="#FBBC05" d="M10.3 28.6c-.5-1.5-.8-3-.8-4.6s.3-3.1.8-4.6l-7.8-6.1C.9 16.5 0 20.1 0 24s.9 7.5 2.5 10.7l7.8-6.1z"/><path fill="#34A853" d="M24 48c6.1 0 11.3-2 15-5.5l-7.1-5.5c-2 1.3-4.6 2.2-7.9 2.2-6.4 0-11.8-3.7-13.7-9l-7.8 6.1C6.4 42.6 14.6 48 24 48z"/></svg>
        Continue with Google
      </button>
      <div class="foothint">Save your watchlist and sync across devices.</div>
    </div>

    <div data-view="acct" style="display:none">
      <div class="acct">
        <div class="av" data-avatar>A</div>
        <h3 data-accname>Hi</h3>
        <div class="em" data-accemail></div>
        <div class="vnote" data-vnote style="display:none">
          <b>Verify your email.</b> We sent a link to <span data-vemail></span> — click it to confirm your account.
          <div class="vrow">
            <button type="button" data-resend>Resend email</button>
            <button type="button" data-vcheck>I've verified</button>
          </div>
          <div class="vmsg" data-vmsg></div>
        </div>
        <div class="row">
          <a class="primary" href="index.html" style="text-align:center;text-decoration:none;display:block">Open the calendar →</a>
          <button class="ghost" data-signout type="button">Sign out</button>
        </div>
        <button class="dellink" data-delopen type="button">Delete account</button>
        <div class="delbox" data-delbox style="display:none">
          <b>Delete your account permanently?</b>
          <p>Your account and synced watchlist access will be removed. This cannot be undone.</p>
          <div data-delpw-wrap>
            <input type="password" data-delpw placeholder="Retype your password to confirm" autocomplete="current-password" />
          </div>
          <div class="vrow">
            <button type="button" data-delcancel>Cancel</button>
            <button type="button" class="delconfirm" data-delconfirm>Delete forever</button>
          </div>
          <div class="vmsg" data-delmsg></div>
        </div>
      </div>
    </div>
  </div>`;
document.addEventListener("DOMContentLoaded", () => document.body.appendChild(root));
if (document.body) document.body.appendChild(root);

const q = (s) => root.querySelector(s);
let mode = "signin";
// Message to show after an auth-state reset (signup/blocked-signin sign the user out, which
// re-renders the form and would otherwise wipe the explanation).
let _pendingMsg = null;

// Gate mode: when the auto-prompt opens for a signed-out visitor, the modal is MANDATORY —
// no close button, no backdrop dismiss. It unlocks (and closes) only on successful sign-in.
let _gated = false;
function open(){ root.classList.add("on"); const x=q("[data-close]"); if(x) x.style.display=_gated?"none":""; }
function close(){ if(_gated && !auth.currentUser) return;   // locked until signed in
  root.classList.remove("on"); q("[data-msg]").textContent="";
  // always re-mask the password when the modal closes
  const pw=q("[data-password]"); if(pw){ pw.type="password"; } const tg=q("[data-pwtoggle]"); if(tg){ tg.textContent="Show"; } }
function setMode(m){
  mode = m;
  q('[data-tab="signin"]').classList.toggle("active", m==="signin");
  q('[data-tab="signup"]').classList.toggle("active", m==="signup");
  q("[data-namewrap]").style.display = m==="signup" ? "block" : "none";
  q("[data-forgot]").style.display = m==="signin" ? "inline-block" : "none";
  q("[data-submit]").textContent = m==="signup" ? "Create account" : "Sign in";
  q("[data-title]").textContent = m==="signup" ? "Create your account" : "Welcome back";
  q("[data-password]").setAttribute("autocomplete", m==="signup" ? "new-password" : "current-password");
  q("[data-msg]").textContent = "";
}
function showError(e){
  const map = {
    "auth/invalid-credential":"Wrong email or password.",
    "auth/invalid-email":"That email doesn’t look right.",
    "auth/email-already-in-use":"An account with this email already exists — try signing in.",
    "auth/weak-password":"Password should be at least 6 characters.",
    "auth/popup-closed-by-user":"Google sign-in was cancelled.",
    "auth/operation-not-allowed":"This sign-in method isn’t enabled yet in Firebase."
  };
  const m = q("[data-msg]"); m.className = "msg err";
  m.textContent = map[e?.code] || (e?.message || "Something went wrong.").replace("Firebase: ","");
}

q("[data-close]").onclick = close;
root.addEventListener("click", (e) => { if (e.target === root) close(); });
q('[data-tab="signin"]').onclick = () => setMode("signin");
q('[data-tab="signup"]').onclick = () => setMode("signup");

q("[data-form]").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = q("[data-email]").value.trim();
  const pw = q("[data-password]").value;
  q("[data-submit]").disabled = true; q("[data-msg]").textContent = "";
  try {
    if (mode === "signup") {
      const cred = await createUserWithEmailAndPassword(auth, email, pw);
      try { window.erTrack && window.erTrack("sign_up", { method: "password" }); } catch (e) {}
      const nm = q("[data-name]").value.trim();
      if (nm) await updateProfile(cred.user, { displayName: nm });
      // HARD verification: send the link, then sign the user straight back out. The account can't
      // be used until the emailed link is clicked and they sign in again. Surface send failures
      // honestly (Firebase rate-limits verification emails after repeated attempts).
      let vErr = null;
      try { await sendEmailVerification(cred.user); } catch (e) { vErr = e; }
      _pendingMsg = vErr
        ? { cls: "msg err", text: (vErr.code === "auth/too-many-requests")
            ? "Account created, but we couldn't email the link yet (too many attempts — Firebase rate limit). Wait ~1 hour, then sign in and we'll resend it."
            : "Account created, but the verification email failed to send (" + (vErr.code || "error") + "). Sign in later and we'll resend it." }
        : { cls: "msg ok", text: "Account created! We sent a verification link to " + email + " — click it, then sign in." };
      await signOut(auth);
    } else {
      const cred = await signInWithEmailAndPassword(auth, email, pw);
      try { window.erTrack && window.erTrack("login", { method: "password" }); } catch (e) {}
      const isPw = cred.user.providerData.some((p) => p.providerId === "password");
      if (isPw && !cred.user.emailVerified) {
        // Unverified accounts may not sign in. Send a fresh link (best effort) and bounce them.
        let sent = true;
        try { await sendEmailVerification(cred.user); } catch (e) { sent = false; }
        _pendingMsg = { cls: "msg err", text: sent
          ? "Your email isn't verified yet. We just sent a new link to " + email + " — click it, then sign in."
          : "Your email isn't verified yet. Check your inbox (and spam) for the earlier link, then sign in." };
        await signOut(auth);
      }
    }
  } catch (err) { showError(err); }
  finally { q("[data-submit]").disabled = false; }
});

q("[data-google]").onclick = async () => {
  try {
    const res = await signInWithPopup(auth, new GoogleAuthProvider());
    const isNew = res && res.user && res.user.metadata && res.user.metadata.creationTime === res.user.metadata.lastSignInTime;
    try { window.erTrack && window.erTrack(isNew ? "sign_up" : "login", { method: "google" }); } catch (e) {}
  }
  catch (err) { showError(err); }
};

q("[data-forgot]").onclick = async () => {
  const email = q("[data-email]").value.trim();
  const m = q("[data-msg]");
  if (!email) { m.className = "msg err"; m.textContent = "Enter your email first, then tap reset."; return; }
  try { await sendPasswordResetEmail(auth, email); m.className = "msg ok"; m.textContent = "Password reset email sent."; }
  catch (err) { showError(err); }
};

q("[data-signout]").onclick = () => signOut(auth);

/* account deletion — requires re-entering the password (or a Google re-auth popup) first */
q("[data-delopen]").onclick = () => {
  q("[data-delbox]").style.display = "block";
  q("[data-delopen]").style.display = "none";
  const isPw = auth.currentUser && auth.currentUser.providerData.some((p) => p.providerId === "password");
  q("[data-delpw-wrap]").style.display = isPw ? "block" : "none";
  q("[data-delpw]").value = ""; q("[data-delmsg]").textContent = "";
};
q("[data-delcancel]").onclick = () => {
  q("[data-delbox]").style.display = "none";
  q("[data-delopen]").style.display = "";
};
q("[data-delconfirm]").onclick = async () => {
  const user = auth.currentUser; if (!user) return;
  const m = q("[data-delmsg]"); m.style.color = "#F87171"; m.textContent = "";
  const btn = q("[data-delconfirm]"); btn.disabled = true;
  try {
    // Fresh re-authentication is REQUIRED before deletion: password accounts must retype their
    // password; Google accounts confirm through a Google popup (they have no password).
    const isPw = user.providerData.some((p) => p.providerId === "password");
    if (isPw) {
      const pw = q("[data-delpw]").value;
      if (!pw) { m.textContent = "Enter your password to confirm."; btn.disabled = false; return; }
      await reauthenticateWithCredential(user, EmailAuthProvider.credential(user.email, pw));
    } else {
      await reauthenticateWithPopup(user, new GoogleAuthProvider());
    }
    // Remove the Firestore mirror BEFORE deleting auth (rules require the user's own uid).
    try { await deleteDoc(doc(_fs, "users", user.uid)); } catch (e) {}
    await deleteUser(user);
    _pendingMsg = { cls: "msg ok", text: "Your account has been deleted." };
  } catch (err) {
    const c = err && err.code;
    m.textContent = c === "auth/invalid-credential" || c === "auth/wrong-password" ? "Wrong password."
      : c === "auth/too-many-requests" ? "Too many attempts — try again in a few minutes."
      : c === "auth/popup-closed-by-user" ? "Confirmation was cancelled."
      : "Couldn't delete the account (" + (c || "error") + ").";
  }
  btn.disabled = false;
};

/* show/hide password */
q("[data-pwtoggle]").onclick = () => {
  const inp = q("[data-password]");
  const show = inp.type === "password";
  inp.type = show ? "text" : "password";
  q("[data-pwtoggle]").textContent = show ? "Hide" : "Show";
  q("[data-pwtoggle]").setAttribute("aria-label", show ? "Hide password" : "Show password");
  inp.focus();
};

/* email-verification actions */
q("[data-resend]").onclick = async () => {
  const m = q("[data-vmsg]");
  try { await sendEmailVerification(auth.currentUser); m.style.color = "#34D399"; m.textContent = "Verification email sent — check your inbox (and spam)."; }
  catch (e) { m.style.color = "#F87171"; m.textContent = (e && e.code === "auth/too-many-requests") ? "Too many requests — try again in a few minutes." : "Couldn't send just now — try again shortly."; }
};
q("[data-vcheck]").onclick = async () => {
  const m = q("[data-vmsg]");
  try {
    await auth.currentUser.reload();
    if (auth.currentUser.emailVerified) { q("[data-vnote]").style.display = "none"; }
    else { m.style.color = "#F87171"; m.textContent = "Not verified yet — click the link in the email first."; }
  } catch (e) {}
};

/* auth state → swap modal view + update the nav trigger label */
onAuthStateChanged(auth, (user) => {
  const trigger = document.getElementById("authTrigger");
  // Hide "Create account" / sign-in CTAs across the page when signed in.
  document.querySelectorAll("[data-auth-open]").forEach((el) => { el.style.display = user ? "none" : ""; });
  if (user) {
    _mirrorUser(user);
    _wlSync(user);
    const nm = user.displayName || user.email.split("@")[0];
    q('[data-view="form"]').style.display = "none";
    q('[data-view="acct"]').style.display = "block";
    q("[data-accname]").textContent = "Hi, " + nm;
    q("[data-accemail]").textContent = user.email;
    q("[data-avatar]").textContent = (nm[0] || "A").toUpperCase();
    if (trigger) trigger.textContent = nm;
    // Verification notice: only for email/password accounts that haven't clicked the link yet.
    // Google sign-ins arrive pre-verified, so they never see this.
    const needsVerify = !user.emailVerified && user.providerData.some((p) => p.providerId === "password");
    q("[data-vnote]").style.display = needsVerify ? "block" : "none";
    if (needsVerify) { q("[data-vemail]").textContent = user.email; q("[data-vmsg]").textContent = ""; }
    q("[data-delbox]").style.display = "none"; q("[data-delopen]").style.display = "";
    // Signed in: release the gate. If the mandatory prompt was up, close it so they land in the calendar.
    if (_gated) { _gated = false; const x=q("[data-close]"); if(x) x.style.display=""; if (root.classList.contains("on")) close(); }
  } else {
    q('[data-view="form"]').style.display = "block";
    q('[data-view="acct"]').style.display = "none";
    setMode("signin");
    if (trigger) trigger.textContent = "Sign in";
    if (_pendingMsg) { const m = q("[data-msg]"); m.className = _pendingMsg.cls; m.textContent = _pendingMsg.text; _pendingMsg = null; }
  }
});

/* wire triggers */
function bindOpeners(){
  const t = document.getElementById("authTrigger");
  if (t) t.addEventListener("click", (e) => { e.preventDefault(); open(); });
  document.querySelectorAll("[data-auth-open]").forEach((el) =>
    el.addEventListener("click", (e) => { e.preventDefault(); setMode(el.getAttribute("data-auth-open") === "signup" ? "signup" : "signin"); open(); })
  );
}
if (document.readyState !== "loading") bindOpeners();
else document.addEventListener("DOMContentLoaded", bindOpeners);
window.openAuth = (m) => { if (m) setMode(m); open(); };

// Auto-open the sign-in / create-account popup ~5s after landing on the calendar
// home page — only when signed out, and once per browser session so it isn't nagging.
(function autoPrompt(){
  // Fire on the home page OR on the calendar app itself (served at /app.html — detected by #calGrid),
  // so moving/renaming the calendar page never silently disables the prompt.
  const isCalendar = !!document.getElementById("calGrid");
  const isHome = isCalendar || location.pathname.endsWith("/") || /\/(index|app|app_slim)\.html$/.test(location.pathname);
  if (!isHome) return;
  try { if (sessionStorage.getItem("er_auth_prompted")) return; } catch (e) {}
  setTimeout(() => {
    if (root.classList.contains("on")) return;   // already open
    if (auth.currentUser) return;                 // already signed in
    try { sessionStorage.setItem("er_auth_prompted", "1"); } catch (e) {}
    _gated = true;                                // MANDATORY: can't be dismissed until signed in
    setMode("signin");
    open();
  }, 5000);
})();
