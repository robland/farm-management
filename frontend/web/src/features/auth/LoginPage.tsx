import { NetworkError } from "@fms/sync-core";
import { type FormEvent, type ReactNode, useState } from "react";

import { ApiError, type ApiClient, type Session } from "../../api/client";
import { Button, ErrorMessage, Field, PasswordField } from "../../ui/components";

export function LoginPage(props: { api: ApiClient; onLoggedIn: (s: Session) => void }): ReactNode {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!identifier.trim() || !password) {
      setError("Identifiant et mot de passe obligatoires.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      props.onLoggedIn(await props.api.login(identifier.trim(), password));
    } catch (err) {
      if (err instanceof NetworkError) {
        setError("Serveur injoignable. La première connexion sur cet appareil nécessite le réseau.");
      } else if (err instanceof ApiError) setError("Identifiants invalides.");
      else throw err;
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-16 max-w-sm p-4">
      <h1 className="text-2xl font-semibold">Gestion agricole</h1>
      <p className="mb-6 text-sm text-stone-600">Connectez-vous pour accéder à vos exploitations.</p>
      <form onSubmit={submit} className="flex flex-col gap-4 rounded-lg border border-stone-200 bg-white p-4 shadow-sm"
            noValidate>
        <Field label="E-mail ou téléphone" value={identifier} autoComplete="username" autoCapitalize="none"
               hint="Téléphone au format international, avec l'indicatif du pays (+…)."
               onChange={(e) => setIdentifier(e.target.value)} />
        <PasswordField label="Mot de passe" value={password} autoComplete="current-password"
                       onChange={(e) => setPassword(e.target.value)} />
        {error && <ErrorMessage>{error}</ErrorMessage>}
        <Button type="submit" disabled={busy}>{busy ? "Connexion…" : "Se connecter"}</Button>
      </form>
    </main>
  );
}
