#!/usr/bin/env sh
# Add someone's SSH public key to this account (make ssh-add). Asks for the key on the terminal,
# checks it, refuses duplicates, and writes it with the options that forbid tunnelling: the key is
# for running commands, nothing else. Remove a key later with: make ssh-remove
set -eu

AUTHORIZED="$HOME/.ssh/authorized_keys"
OPTIONS="no-port-forwarding,no-agent-forwarding,no-X11-forwarding"

printf 'Clé publique à autoriser (une ligne « ssh-ed25519 AAAA… commentaire ») :\n> '
IFS= read -r KEY
KEY=$(printf '%s' "$KEY" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
[ -n "$KEY" ] || { echo "Aucune clé saisie." >&2; exit 1; }

# A bare key, or one that already carries options: keep only the key part.
case "$KEY" in
  ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*|sk-ssh-ed25519@openssh.com\ *|sk-ecdsa-*) ;;
  *) KEY=$(printf '%s' "$KEY" | sed -E 's/^[^ ]+ (ssh-|ecdsa-|sk-)/\1/') ;;
esac

FINGERPRINT=$(printf '%s\n' "$KEY" | ssh-keygen -lf /dev/stdin 2>/dev/null) \
  || { echo "Ce n'est pas une clé publique SSH valide." >&2; exit 1; }

KEY_BODY=$(printf '%s' "$KEY" | awk '{print $1" "$2}')
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
touch "$AUTHORIZED" && chmod 600 "$AUTHORIZED"
if grep -qF "$KEY_BODY" "$AUTHORIZED"; then
  echo "Déjà présente : $FINGERPRINT"
  exit 0
fi

printf '%s %s\n' "$OPTIONS" "$KEY" >> "$AUTHORIZED"
echo "Ajoutée pour $(id -un)@$(hostname) : $FINGERPRINT"
echo "Pour la retirer : make ssh-remove   (ou éditer $AUTHORIZED)"
