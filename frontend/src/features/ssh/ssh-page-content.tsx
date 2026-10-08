import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { sinceLabel } from "@/features/alerts/alerts-api";
import { groupByDay } from "@/lib/day-groups";
import { useNow } from "@/lib/use-now";
import { identityLabel, SSH_LIMIT, summarizeSsh, type Outcome, type SshEvent } from "./ssh-api";
import { SshEventRow } from "./ssh-event-row";
import { useSshEvents } from "./use-ssh-events";

type OutcomeFilter = "all" | Outcome;

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</p>
        <p className="mt-1 truncate text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function matches(event: SshEvent, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return [event.ip, event.username, event.key_comment ?? "", event.key_fingerprint ?? ""].some(
    (v) => v.toLowerCase().includes(q),
  );
}

/** The /ssh page: a summary, outcome and text filters, the connections as a day timeline. */
export function SshPageContent({ nowMs }: { nowMs?: number }) {
  const { status, events } = useSshEvents();
  const tick = useNow();
  const now = nowMs ?? tick;
  const [outcome, setOutcome] = useState<OutcomeFilter>("all");
  const [query, setQuery] = useState("");

  const filtered = events
    .filter((e) => outcome === "all" || e.outcome === outcome)
    .filter((e) => matches(e, query.trim()));
  const summary = summarizeSsh(events, now);

  return (
    <section aria-labelledby="ssh-title" className="space-y-5">
      <h1 id="ssh-title" className="text-2xl font-semibold">
        Accès SSH
      </h1>

      {status === "ready" && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Connexions 24 h" value={String(summary.accepted24h)} hint="acceptées" />
          <Stat
            label="Refus 24 h"
            value={String(summary.refused24h)}
            hint={summary.refused24h > 0 ? "ouvrent une alerte SSH" : "aucune tentative refusée"}
          />
          <Stat
            label="Dernière acceptée"
            value={summary.lastAccepted ? identityLabel(summary.lastAccepted) : "–"}
            hint={
              summary.lastAccepted
                ? `il y a ${sinceLabel(now - Date.parse(summary.lastAccepted.occurred_at))}`
                : undefined
            }
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <ToggleGroup
          type="single"
          value={outcome}
          onValueChange={(v) => v && setOutcome(v as OutcomeFilter)}
          aria-label="Résultat"
          variant="outline"
        >
          <ToggleGroupItem value="all">Toutes</ToggleGroupItem>
          <ToggleGroupItem value="accepted">Acceptées</ToggleGroupItem>
          <ToggleGroupItem value="refused">Refusées</ToggleGroupItem>
        </ToggleGroup>
        <Input
          type="search"
          aria-label="Rechercher"
          placeholder="IP, mail, utilisateur"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-56"
        />
      </div>

      {status === "loading" && (
        <Skeleton role="status" aria-label="Chargement des connexions" className="h-40 w-full" />
      )}
      {status === "error" && <p className="text-destructive">Journal SSH indisponible.</p>}
      {status === "ready" && filtered.length === 0 && (
        <p className="text-muted-foreground">Aucune connexion</p>
      )}
      {status === "ready" && events.length >= SSH_LIMIT && (
        <p className="text-muted-foreground text-sm">
          Seules les {SSH_LIMIT} connexions les plus récentes sont affichées.
        </p>
      )}

      {filtered.length > 0 && (
        <section aria-labelledby="ssh-history-title" className="space-y-4">
          <h2 id="ssh-history-title" className="text-sm font-medium">
            Historique
          </h2>
          {groupByDay(filtered, now, (e) => e.occurred_at).map((group) => (
            <div key={group.label} className="relative pl-5">
              <span
                aria-hidden="true"
                className="bg-border absolute top-2 bottom-2 left-1.5 w-px"
              />
              <h3 className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
                <span
                  aria-hidden="true"
                  className="bg-muted-foreground/60 absolute top-1.5 left-0 size-3 rounded-full ring-4 ring-[var(--background)]"
                />
                {group.label}
              </h3>
              <ul className="divide-y" aria-label={`Connexions, ${group.label}`}>
                {group.items.map((e) => (
                  <SshEventRow key={e.id} event={e} />
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}
    </section>
  );
}
