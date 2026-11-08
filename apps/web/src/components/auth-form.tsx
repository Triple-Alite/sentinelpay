"use client";

import { FormEvent, useState } from "react";

type AuthMode = "login" | "register";

export function AuthForm({ mode }: { mode: AuthMode }) {
  const isRegister = mode === "register";
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = event.currentTarget;
    const values = new FormData(form);
    const password = String(values.get("password") ?? "");

    if (isRegister && password !== values.get("confirm_password")) {
      setError("Passwords do not match.");
      return;
    }

    const payload = isRegister
      ? {
          full_name: String(values.get("full_name") ?? "").trim(),
          business_name: String(values.get("business_name") ?? "").trim(),
          email: String(values.get("email") ?? "").trim(),
          password,
          country: String(values.get("country") ?? ""),
          website: String(values.get("website") ?? "").trim() || null,
        }
      : {
          email: String(values.get("email") ?? "").trim(),
          password,
        };

    setSubmitting(true);
    try {
      const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
      const response = await fetch(`${apiUrl}/api/v1/auth/${mode}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        const detail = result?.detail;
        setError(Array.isArray(detail) ? detail[0]?.msg ?? "Check the submitted details." : detail ?? "Could not authenticate.");
        return;
      }
      window.location.assign("/");
    } catch {
      setError("Could not reach SentinelPay. Check that the API is running.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={submit}>
      {isRegister && (
        <>
          <label className="auth-field">
            <span>Full name</span>
            <input name="full_name" autoComplete="name" minLength={2} maxLength={120} required />
          </label>
          <label className="auth-field">
            <span>Business name</span>
            <input name="business_name" autoComplete="organization" minLength={2} maxLength={160} required />
          </label>
        </>
      )}

      <label className="auth-field">
        <span>Email</span>
        <input name="email" type="email" autoComplete="email" maxLength={320} required />
      </label>

      {isRegister && (
        <div className="auth-field-row">
          <label className="auth-field">
            <span>Country</span>
            <select name="country" defaultValue="" required>
              <option value="" disabled>Select</option>
              <option value="US">United States</option>
              <option value="CA">Canada</option>
              <option value="GB">United Kingdom</option>
              <option value="AU">Australia</option>
              <option value="SG">Singapore</option>
              <option value="DE">Germany</option>
              <option value="FR">France</option>
            </select>
          </label>
          <label className="auth-field">
            <span>Website <span className="optional-label">Optional</span></span>
            <input name="website" type="url" autoComplete="url" placeholder="https://" />
          </label>
        </div>
      )}

      <label className="auth-field">
        <span>Password</span>
        <input
          name="password"
          type="password"
          autoComplete={isRegister ? "new-password" : "current-password"}
          minLength={isRegister ? 12 : 1}
          maxLength={128}
          required
        />
        {isRegister && <small>Use at least 12 characters.</small>}
      </label>

      {isRegister && (
        <label className="auth-field">
          <span>Confirm password</span>
          <input name="confirm_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required />
        </label>
      )}

      {isRegister && (
        <label className="terms-field">
          <input name="terms" type="checkbox" required />
          <span>I agree to the terms and privacy policy.</span>
        </label>
      )}

      {error && <p className="auth-error" role="alert">{error}</p>}

      <button className="auth-submit" type="submit" disabled={submitting}>
        {submitting ? "Please wait..." : isRegister ? "Create merchant account" : "Sign in"}
      </button>
    </form>
  );
}