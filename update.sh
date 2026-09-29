#!/usr/bin/env bash
# ==============================================================================
#  ⚡ VALLEN NEXT — AUTO GIT COMMIT & PUSH SCRIPT
#  Created for: vallenmulia99/vallennextproject
# ==============================================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

cleanup() {
    if [ -n "${ASKPASS_FILE:-}" ]; then
        rm -f "$ASKPASS_FILE"
    fi
}
trap cleanup EXIT

# ANSI Color Codes
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

RED="\033[1;31m"
GREEN="\033[1;32m"
YELLOW="\033[1;33m"
BLUE="\033[1;34m"
PURPLE="\033[1;35m"
CYAN="\033[1;36m"
WHITE="\033[1;37m"

BG_GREEN="\033[42;30m"
BG_BLUE="\033[44;37m"
BG_RED="\033[41;37m"

clear 2>/dev/null || true

echo -e "${PURPLE}"
cat << "BANNER"
  ██████╗ ██╗████████╗    ██████╗ ██╗   ██╗███████╗██╗  ██╗
 ██╔════╝ ██║╚══██╔══╝    ██╔══██╗██║   ██║██╔════╝██║  ██║
 ██║  ███╗██║   ██║       ██████╔╝██║   ██║███████╗███████║
 ██║   ██║██║   ██║       ██╔═══╝ ██║   ██║╚════██║██╔══██║
 ╚██████╔╝██║   ██║       ██║     ╚██████╔╝███████║██║  ██║
  ╚═════╝ ╚═╝   ╚═╝       ╚═╝      ╚═════╝ ╚══════╝╚═╝  ╚═╝
BANNER
echo -e "${CYAN}        ⚡ VALLEN NEXT — AUTO GIT COMMITER & PUSHER ⚡${RESET}"
echo -e "${DIM}  ─────────────────────────────────────────────────────────────${RESET}"

# 1. Resolve Token & Target Repo
TOKEN_FILE="${SCRIPT_DIR}/.git_token"

if [ -n "${GITHUB_TOKEN:-}" ]; then
    TOKEN="$GITHUB_TOKEN"
elif [ -f "$TOKEN_FILE" ]; then
    TOKEN="$(cat "$TOKEN_FILE" | tr -d '\r\n ')"
else
    echo -e "${YELLOW}⚠️  File .git_token belum ada.${RESET}"
    read -r -s -p "$(echo -e "${CYAN}[?] Masukkan GitHub Token (ghp_...): ${RESET}")" INPUT_TOKEN
    echo
    TOKEN="$(printf '%s' "$INPUT_TOKEN" | tr -d '\r\n ')"
    if [ -n "$TOKEN" ]; then
        echo "$TOKEN" > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE" 2>/dev/null || true
    fi
fi

if [ -z "$TOKEN" ]; then
    echo -e "${RED}❌ Error: GitHub Token tidak ditemukan! Silakan isi .git_token atau set GITHUB_TOKEN.${RESET}"
    exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/vallenmulia99/vallennextproject.git}"
CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [ -z "$CURRENT_BRANCH" ]; then
    echo -e "${RED}❌ Error: HEAD detached. Checkout branch sebelum update.${RESET}"
    exit 1
fi
if ! git remote get-url origin >/dev/null 2>&1; then
    echo -e "${RED}❌ Error: remote origin tidak ditemukan.${RESET}"
    exit 1
fi
ASKPASS_FILE="$(mktemp)"
cat > "$ASKPASS_FILE" <<'ASKPASS'
#!/usr/bin/env bash
printf '%s\n' "${GIT_TOKEN_FOR_ASKPASS:-}"
ASKPASS
chmod 700 "$ASKPASS_FILE"

git_auth() {
    GIT_TOKEN_FOR_ASKPASS="$TOKEN" GIT_ASKPASS="$ASKPASS_FILE" GIT_TERMINAL_PROMPT=0 \
        git -c credential.username=x-access-token "$@"
}

echo -e "${WHITE}  📂 Direktori : ${CYAN}${SCRIPT_DIR}${RESET}"
echo -e "${WHITE}  🌿 Branch    : ${GREEN}${CURRENT_BRANCH}${RESET}"
echo -e "${WHITE}  🌐 Remote    : ${BLUE}${REPO_URL}${RESET}"
echo -e "${DIM}  ─────────────────────────────────────────────────────────────${RESET}"

# 2. Sync remote state and check Git changes
if ! git_auth fetch origin "${CURRENT_BRANCH}"; then
    echo -e "${RED}❌ Error: gagal mengambil perubahan remote. Cek token, jaringan, dan remote.${RESET}"
    exit 1
fi
STATUS_OUTPUT="$(git status --porcelain)"
BEHIND="$(git rev-list "HEAD..origin/${CURRENT_BRANCH}" --count)"
if [ "$BEHIND" -gt 0 ] && [ -n "$STATUS_OUTPUT" ]; then
    echo -e "${YELLOW}📥 Remote punya $BEHIND commit baru. Simpan perubahan lalu rebase sebelum commit...${RESET}"
    STASH_NAME="update.sh-pre-sync-$(date +%s)"
    git stash push --include-untracked -m "$STASH_NAME" >/dev/null
    if ! git_auth pull --rebase origin "${CURRENT_BRANCH}" >/dev/null 2>&1; then
        git rebase --abort >/dev/null 2>&1 || true
        git stash pop >/dev/null 2>&1 || true
        echo -e "${RED}❌ Error: rebase konflik. Perubahan dikembalikan; selesaikan konflik manual.${RESET}"
        exit 1
    fi
    if ! git stash pop >/dev/null 2>&1; then
        echo -e "${RED}❌ Error: konflik saat mengembalikan perubahan setelah rebase.${RESET}"
        exit 1
    fi
    STATUS_OUTPUT="$(git status --porcelain)"
fi

if [ -z "$STATUS_OUTPUT" ]; then
    # Check if there are unpushed commits
    UNPUSHED="$(git log "origin/${CURRENT_BRANCH}..HEAD" --oneline)"
    if [ -n "$UNPUSHED" ]; then
        echo -e "\n${YELLOW}ℹ️  Tidak ada file baru/berubah, tetapi ada commit yang belum di-push:${RESET}"
        echo -e "${DIM}$UNPUSHED${RESET}\n"
        read -p "$(echo -e "${CYAN}[?] Push commit di atas sekarang? [Y/n]: ${RESET}")" CONFIRM_PUSH
        CONFIRM_PUSH=${CONFIRM_PUSH:-Y}
        if [[ "$CONFIRM_PUSH" =~ ^[Yy]$ ]]; then
            echo -e "\n${YELLOW}⏳ Sinkronisasi dengan remote...${RESET}"
            git_auth fetch origin "${CURRENT_BRANCH}" >/dev/null
            BEHIND="$(git rev-list HEAD..origin/${CURRENT_BRANCH} --count 2>/dev/null || echo "0")"
            if [ "$BEHIND" -gt 0 ]; then
                echo -e "${YELLOW}📥 Remote punya $BEHIND commit baru, pull --rebase dulu...${RESET}"
                git_auth pull --rebase origin "${CURRENT_BRANCH}"
            fi
            echo -e "${YELLOW}⏳ Sedang push ke GitHub...${RESET}"
            git_auth push origin "${CURRENT_BRANCH}"
            echo -e "\n${BG_GREEN} ✓ PUSH BERHASIL! ${RESET}\n"
            exit 0
        else
            echo -e "${DIM}Dibatalkan.${RESET}\n"
            exit 0
        fi
    else
        echo -e "\n${GREEN}✨ Working directory bersih! Tidak ada perubahan yang perlu di-commit.${RESET}"
        echo -e "${DIM}Repo sudah up-to-date dengan origin/${CURRENT_BRANCH}.${RESET}\n"
        exit 0
    fi
fi

# 3. Display Detailed Changes with Red & Green
echo -e "\n${BOLD}${WHITE}📋 DAFTAR PERUBAHAN FILE:${RESET}"
echo -e "${DIM}-------------------------------------------------------------${RESET}"

MODIFIED_COUNT=0
ADDED_COUNT=0
DELETED_COUNT=0
UNTRACKED_COUNT=0

while IFS= read -r line; do
    CODE="${line:0:2}"
    FILE="${line:3}"
    if [[ "$CODE" =~ M ]]; then
        echo -e "  ${YELLOW}~ MODIFIED  :${RESET} ${WHITE}${FILE}${RESET}"
        ((MODIFIED_COUNT++)) || true
    elif [[ "$CODE" =~ A ]]; then
        echo -e "  ${GREEN}+ ADDED     :${RESET} ${GREEN}${FILE}${RESET}"
        ((ADDED_COUNT++)) || true
    elif [[ "$CODE" =~ D ]]; then
        echo -e "  ${RED}- DELETED   :${RESET} ${RED}${FILE}${RESET}"
        ((DELETED_COUNT++)) || true
    elif [[ "$CODE" == "??" ]]; then
        echo -e "  ${CYAN}+ UNTRACKED :${RESET} ${CYAN}${FILE}${RESET}"
        ((UNTRACKED_COUNT++)) || true
    else
        echo -e "  ${PURPLE}* CHANGE    :${RESET} ${WHITE}${FILE}${RESET}"
    fi
done <<< "$STATUS_OUTPUT"

echo -e "${DIM}-------------------------------------------------------------${RESET}"
echo -e "  Total: ${GREEN}${ADDED_COUNT} Tambah${RESET} | ${YELLOW}${MODIFIED_COUNT} Ubah${RESET} | ${RED}${DELETED_COUNT} Hapus${RESET} | ${CYAN}${UNTRACKED_COUNT} Baru${RESET}"

# 4. Preview Git Diff Stat
echo -e "\n${BOLD}${WHITE}📊 STATISTIK PERUBAHAN BARIS KODE:${RESET}"
git diff --stat 2>/dev/null || true
echo -e "${DIM}─────────────────────────────────────────────────────────────${RESET}"

# 5. Prompt for Commit Message
echo ""
echo -e "${BOLD}${CYAN}✏️  MASUKKAN PESAN COMMIT:${RESET}"
echo -e "${DIM}Contoh: update fix ide / feat: new layout / fix: terminal pty${RESET}"
read -r -p "$(echo -e "${BOLD}${GREEN}➤ Commit Name: ${RESET}")" COMMIT_MSG

if [ -z "$COMMIT_MSG" ]; then
    DEFAULT_MSG="update: $(date '+%Y-%m-%d %H:%M:%S') - auto sync"
    COMMIT_MSG="$DEFAULT_MSG"
    echo -e "${DIM}  (Menggunakan default: \"${COMMIT_MSG}\")${RESET}"
fi

echo -e "\n${DIM}─────────────────────────────────────────────────────────────${RESET}"
echo -e "${BOLD}${YELLOW}🚀 PROSES PUSH DIMULAI...${RESET}"

# 6. Stage All Files
echo -ne "  [1/3] Menambahkan semua perubahan (git add)... "
git add --all :/
echo -e "${GREEN}✓ SELESAI${RESET}"

# 7. Commit
echo -ne "  [2/3] Menyimpan commit lokal... "
if ! git diff --cached --quiet; then
    git commit -m "$COMMIT_MSG" > /dev/null
else
    echo -e "${YELLOW}tidak ada perubahan staged${RESET}"
    exit 0
fi
COMMIT_HASH="$(git rev-parse --short HEAD)"
echo -e "${GREEN}✓ [${COMMIT_HASH}]${RESET}"

# 8. Sync & Push to GitHub
echo -ne "  [3/4] Fetch remote changes... "
if ! git_auth fetch origin "${CURRENT_BRANCH}" > /dev/null 2>&1; then
    echo -e "${RED}gagal${RESET}"
    echo -e "${RED}❌ Error: gagal mengambil perubahan remote. Commit lokal tetap tersimpan.${RESET}"
    exit 1
fi
echo -e "${GREEN}✓${RESET}"

if ! git diff --quiet "origin/${CURRENT_BRANCH}"...HEAD; then
    echo -e "${YELLOW}ℹ️  Local commit siap dikirim.${RESET}"
fi

echo -ne "  [4/4] Mengirim (push) ke GitHub (${CURRENT_BRANCH})... "
git_auth push origin "${CURRENT_BRANCH}" > /dev/null 2>&1
echo -e "${GREEN}✓ SUKSES!${RESET}"

# 9. Big Success Banner
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}║                                                            ║${RESET}"
echo -e "${GREEN}║       🎉  ${BOLD}BERHASIL DI-PUSH KE GITHUB SECARA LENGKAP!${RESET}${GREEN}       ║${RESET}"
echo -e "${GREEN}║                                                            ║${RESET}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${RESET}"
echo -e "  ${WHITE}📦 Commit Hash :${RESET} ${YELLOW}${COMMIT_HASH}${RESET}"
echo -e "  ${WHITE}📝 Pesan       :${RESET} ${CYAN}${COMMIT_MSG}${RESET}"
echo -e "  ${WHITE}🌿 Branch      :${RESET} ${GREEN}${CURRENT_BRANCH}${RESET}"
echo -e "  ${WHITE}🌐 Repository  :${RESET} ${BLUE}https://github.com/vallenmulia99/vallennextproject${RESET}"
echo -e "  ${WHITE}⏰ Waktu       :${RESET} ${DIM}$(date '+%Y-%m-%d %H:%M:%S')${RESET}"
echo ""
echo -e "${DIM}Repo sudah tersinkronisasi 100% dengan GitHub!${RESET}\n"
