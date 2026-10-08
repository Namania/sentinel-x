#!/usr/bin/env sh
# List this account's authorized SSH keys and remove one (make ssh-remove).
set -eu
AUTHORIZED="$HOME/.ssh/authorized_keys"
[ -s "$AUTHORIZED" ] || { echo "Aucune clé autorisée."; exit 0; }
echo "Clés autorisées :"
n=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  n=$((n + 1))
  printf '  %d) %s\n' "$n" "$(printf '%s\n' "$line" | sed -E 's/^[^ ]+ (ssh-|ecdsa-|sk-)/\1/' | ssh-keygen -lf /dev/stdin 2>/dev/null || echo "$line")"
done < "$AUTHORIZED"
printf 'Numéro à retirer (vide pour annuler) : '
IFS= read -r CHOICE
[ -n "$CHOICE" ] || exit 0
case "$CHOICE" in ''|*[!0-9]*) echo "Numéro invalide." >&2; exit 1;; esac
[ "$CHOICE" -ge 1 ] && [ "$CHOICE" -le "$n" ] || { echo "Numéro hors liste." >&2; exit 1; }
TMP=$(mktemp) && awk -v k="$CHOICE" 'NF { i++; if (i == k) next } { print }' "$AUTHORIZED" > "$TMP"
cat "$TMP" > "$AUTHORIZED" && rm -f "$TMP"
echo "Clé $CHOICE retirée."
