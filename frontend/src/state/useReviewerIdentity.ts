import { useEffect, useState } from 'react';

const STORAGE_KEY = 'plimsoll.reviewerIdentity.v1';

interface ReviewerIdentity {
  reviewerName: string;
  approvalRoleCode: string;
}

function load(): ReviewerIdentity {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { reviewerName: '', approvalRoleCode: '' };
    return { reviewerName: '', approvalRoleCode: '', ...(JSON.parse(raw) as Partial<ReviewerIdentity>) };
  } catch {
    return { reviewerName: '', approvalRoleCode: '' };
  }
}

/** The one "may this be signed" check the UI uses (ReviewBar's button, its
 * Enter shortcut, export, chain sign-off). The server re-checks it anyway —
 * this only decides whether a submit is attempted at all. */
export function hasReviewerIdentity(reviewerName: string, approvalRoleCode: string): boolean {
  return reviewerName.trim() !== '' && approvalRoleCode !== '';
}

/** Who is reviewing right now (§20 reviewer_name + approval_role_code) —
 * set once, reused across every ReviewBar submission in this browser. This
 * is a UI convenience default only; each written event still snapshots
 * whatever was selected at submit time (approval_role_label_snapshot), so
 * editing config later never rewrites history. Distinct from the app-level
 * login role in Settings → 角色 (Risk 1 disambiguation). */
export function useReviewerIdentity() {
  const [identity, setIdentity] = useState<ReviewerIdentity>(() => load());

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
  }, [identity]);

  return {
    reviewerName: identity.reviewerName,
    approvalRoleCode: identity.approvalRoleCode,
    setReviewerName: (reviewerName: string) => setIdentity((prev) => ({ ...prev, reviewerName })),
    setApprovalRoleCode: (approvalRoleCode: string) => setIdentity((prev) => ({ ...prev, approvalRoleCode })),
  };
}
