# GitHub Push Checklist

## Summary of Changes

This guide shows exactly what to push to GitHub and what to exclude.

---

## ✅ Files to Include in Commit

### New Documentation Files
- ✅ `GITHUB_PUSH_GUIDE.md` - Strategy for handling large files
- ✅ `SETUP_AND_DEPLOYMENT.md` - Complete setup instructions  
- ✅ `GCP_DEPLOYMENT_GUIDE.md` - Production deployment (10 phases)

### New Scripts
- ✅ `setup.sh` - Automated development setup (executable)
- ✅ `fpa_web/scripts/download_checkpoint.py` - Checkpoint downloader
- ✅ `fpa_web/scripts/__init__.py` - Package marker

### Modified Core Files
- ✅ `.gitignore` - Updated to exclude *.pt files and large assets
- ✅ `fpa_web/config/settings/base.py` - Updated LOGIN_REDIRECT_URL
- ✅ `fpa_web/templates/base.html` - Fixed logout button (POST form)
- ✅ `fpa_web/templates/registration/login.html` - Fixed login form action
- ✅ `fpa_web/apps/scans/models.py` - Model and parameter documentation
- ✅ `fpa_web/apps/scans/tasks.py` - CPU-optimized inference implementation
- ✅ `fpa_web/apps/scans/migrations/0003_*.py` - Database migration for new fields

### Optional Documentation (Nice to Have)
- ⚠️ `fpa_web/CPU_OPTIMIZATION_SUMMARY.md` - CPU optimization notes
- ⚠️ `fpa_web/CPU_PROCESSING.md` - CPU processing details
- ⚠️ `fpa_web/.env.cpu.example` - Example environment variables

---

## ❌ Files to EXCLUDE (Already in .gitignore)

### Large Model Files
- ❌ `lingbot-map.pt` (4.6GB) - Downloaded automatically, not in repo
- ❌ `/tmp/checkpoints/` - Checkpoint directory
- ❌ Any `*.pt`, `*.pth`, `*.bin` files

### Generated Files
- ❌ `fpa_web/db.sqlite3` - Database (regenerated on setup)
- ❌ `fpa_web/media/scans/*/` - User-generated scan artifacts
- ❌ `fpa_web/__pycache__/` - Python bytecode
- ❌ `venv/` - Virtual environment

### Sensitive Files
- ❌ `.env` - Environment variables
- ❌ `.env.local` - Local overrides
- ❌ `key.json` - GCP credentials
- ❌ Any private keys or secrets

---

## Step-by-Step Push Instructions

### Step 1: Verify Nothing Large is Staged

```bash
cd /workspaces/ss-tool

# Check file sizes (should all be < 100MB)
du -sh fpa_web/media/scans/*
du -sh fpa_web/db.sqlite3

# Verify no .pt files are tracked
git ls-files | grep -i "\.pt$"
```

### Step 2: Add All Changes (except excluded files)

```bash
# Add new files and modifications
git add .

# Verify nothing large is staged
git diff --cached --stat | sort -k3 -rn | head -20
```

Expected output (should be all small files):
```
 GITHUB_PUSH_GUIDE.md                      | 800 +
 SETUP_AND_DEPLOYMENT.md                   | 500 +
 GCP_DEPLOYMENT_GUIDE.md                   |1200 +
 setup.sh                                  |  80 +
 fpa_web/scripts/download_checkpoint.py    |  70 +
 fpa_web/config/settings/base.py           |  20 +
 ...
```

### Step 3: Create Commit Message

```bash
git commit -m "Add deployment infrastructure and large file handling

Core Additions:
- Add GCP deployment guide (10 phases, Option A architecture)
- Add GitHub push guide for large file handling strategy
- Add complete setup and deployment documentation
- Add automated setup.sh script
- Add checkpoint downloader script (downloads from HuggingFace)

Infrastructure:
- Update .gitignore to exclude *.pt files and model checkpoints
- Add fpa_web/scripts/ package for utility scripts
- Add example environment files for CPU optimization

Fixes:
- Fix Django login/logout functionality
  * Change logout button from GET link to POST form
  * Add explicit action attribute to login form
  * Update LOGIN_REDIRECT_URL to 'sites:list' named URL
  
Model & Inference:
- Optimize inference for CPU with gradient checkpointing
- Add proper float32 precision handling for CPU
- Document parameter persistence and validation
- Add database migration for enhanced task tracking

Documentation:
- Add comprehensive deployment guide for Option A
- Document checkpoint download process
- Add troubleshooting guides and cost breakdown
- Document git/large file strategy
- Add FAQ and quick-start guides

The 4.6GB lingbot-map.pt checkpoint is NOT included in this commit.
It is automatically downloaded from HuggingFace Hub during setup."
```

### Step 4: Verify Commit Contents

```bash
# Show what will be committed
git show --stat

# Verify no large files
git ls-files --cached | xargs du -k | sort -rn | head -20
```

### Step 5: Push to GitHub

```bash
git push origin main
```

---

## After Pushing

### Verify on GitHub

1. Go to https://github.com/YOUR_USERNAME/ss-tool
2. Verify all files are there:
   - ✅ `GITHUB_PUSH_GUIDE.md`
   - ✅ `SETUP_AND_DEPLOYMENT.md`
   - ✅ `GCP_DEPLOYMENT_GUIDE.md`
   - ✅ `setup.sh` (should show as executable)
   - ✅ `fpa_web/scripts/download_checkpoint.py`
   - ✅ Updated `.gitignore`
3. Check repo size: Should be ~100-200MB, NOT 4.6GB+
4. Clone in a new test directory to verify:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ss-tool.git
   cd ss-tool
   ./setup.sh  # Should work without issues
   ```

---

## Troubleshooting

### Issue: "Large file found in repository"

If you see this warning:
```
warning: the following file has been removed from the index:
    fpa_web/db.sqlite3
```

This is EXPECTED and OK. The `.gitignore` prevents future commits of these files.

### Issue: Repository is still >1GB

**Check what's taking space:**
```bash
git rev-list --all --objects --disk-usage | sort -k2 -rn | head -20
```

**If you find lingbot-map.pt in history:**
```bash
# Remove from git history (this rewrites the repo)
git filter-branch --tree-filter 'rm -f lingbot-map.pt' HEAD

# Force push (WARNING: does a force push)
git push origin main --force
```

### Issue: Git still tracking db.sqlite3

**Solution:**
```bash
git rm --cached fpa_web/db.sqlite3
git add fpa_web/.gitignore
git commit -m "Remove db.sqlite3 from version control"
git push origin main
```

---

## File Size Reference

Here's what a good commit should look like:

```
Files Changed: ~30-40 files
Total Size: <10MB
Largest files:
  - GITHUB_PUSH_GUIDE.md (~10KB)
  - GCP_DEPLOYMENT_GUIDE.md (~50KB)  
  - SETUP_AND_DEPLOYMENT.md (~30KB)
  - Other files: <10KB each

NO files should be:
  - > 1MB
  - .pt or .pth (model files)
  - db.sqlite3 (database)
  - In media/ directory (except for essential docs)
```

---

## Quick Reference Commands

```bash
# Check what will be pushed
git diff --cached --stat

# Show commit details before pushing
git log -1 --stat

# See total size of staged changes
git diff --cached --stat | awk '{sum+=$4} END {print sum "KB"}'

# Verify no large files are staged
git diff --cached -z | xargs -0 du -k | sort -rn | head -5

# Push with verification
git push origin main --verbose
```

---

## Success Criteria

After pushing, you should see:

✅ All 40+ files successfully uploaded  
✅ Repository size < 200MB (not 4.6GB)  
✅ No "File too large" errors  
✅ lingbot-map.pt NOT in repo  
✅ setup.sh is executable in GitHub UI  
✅ All documentation files visible  
✅ New users can: `git clone → ./setup.sh → works`

