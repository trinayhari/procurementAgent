import { useEffect, useState } from 'react'
import { Box, css } from './lib'
import { previewApproval, executeApproval, ApprovalError } from './api'
import type { ApprovalPreview, ApprovalResult } from './api'

// Standalone screen for the public approval link (#/approve/<token>): the
// award card the agent emailed, with one Approve button. Renders before the
// login gate (the approver may have no account; the token is the credential).
// States: loading, pending (card + button), confirming, done (PO numbers),
// used / expired / unknown link, and a refused award (409, already awarded
// from the dashboard).
type Phase = 'loading' | 'pending' | 'confirming' | 'done' | 'unavailable' | 'error'

const money = (v: number | null | undefined) =>
  typeof v === 'number' ? `$${Math.round(v).toLocaleString('en-US')}` : '$0'

export default function Approve({
  token,
  onDismiss,
}: {
  token: string
  onDismiss: () => void
}) {
  const [preview, setPreview] = useState<ApprovalPreview | null>(null)
  const [result, setResult] = useState<ApprovalResult | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    previewApproval(token)
      .then((p) => {
        if (!alive) return
        setPreview(p)
        setPhase(p.status === 'pending' ? 'pending' : 'unavailable')
      })
      .catch((err) => {
        if (!alive) return
        setError(err instanceof Error ? err.message : 'This approval link is not valid.')
        setPhase(err instanceof ApprovalError && err.status === 404 ? 'unavailable' : 'error')
      })
    return () => { alive = false }
  }, [token])

  const approve = async () => {
    if (phase !== 'pending') return
    setPhase('confirming')
    setError(null)
    try {
      const r = await executeApproval(token)
      setResult(r)
      setPhase('done')
    } catch (err) {
      if (err instanceof ApprovalError && err.status === 410) {
        // Spent or expired between the preview and the click: show why.
        setPreview((p) => (p ? { ...p, status: err.message.toLowerCase().includes('expired') ? 'expired' : 'used' } : p))
        setPhase('unavailable')
        return
      }
      setError(err instanceof Error ? err.message : 'Could not approve the award.')
      setPhase('pending')
    }
  }

  // Kept as strings so a variant can append declarations before css() turns
  // them into a style object (an object concatenated with a string would
  // stringify to "[object Object]" and lose every declaration).
  const cardCss = 'background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:24px'
  const rowCss = 'display:flex;justify-content:space-between;gap:12px;font-size:13px;padding:8px 0;border-top:1px solid var(--border)'
  const buttonCss = 'width:100%;height:40px;border-radius:9px;background:var(--primary);color:var(--on-primary,#fff);font-size:14px;font-weight:600;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:var(--shadow-sm)'
  const card = css(cardCss)
  const h1 = css('margin:0 0 4px;font-size:19px;font-weight:700;letter-spacing:-.01em')
  const sub = css('margin:0 0 18px;font-size:13px;color:var(--text-3)')
  const row = css(rowCss)
  const button = css(buttonCss)

  const unavailableReason = (status?: string | null): string => {
    switch (status) {
      case 'used': return `This award was already approved${preview?.decidedByEmail ? ` by ${preview.decidedByEmail}` : ''}. Nothing more to do.`
      case 'expired': return 'This approval link has expired. Ask Proq for a fresh recommendation from the dashboard.'
      default: return "This approval link isn't valid."
    }
  }

  return (
    <div style={css('min-height:100vh;background:var(--bg);color:var(--text);display:flex;align-items:center;justify-content:center;padding:24px')}>
      <div style={css('width:100%;max-width:440px;animation:pcUp .25s ease both')}>
        <div style={css('display:flex;align-items:center;gap:11px;justify-content:center;margin-bottom:22px')}>
          <img src="/proq-icon.png" alt="Proq" width={38} height={38} style={css('flex:none')} />
          <span style={css('font-size:18px;font-weight:800;letter-spacing:-.01em')}>Proq</span>
        </div>

        {phase === 'loading' ? (
          <div style={css(cardCss + ';text-align:center;color:var(--text-3);font-size:13px')}>
            Loading the award…
          </div>
        ) : phase === 'unavailable' || phase === 'error' ? (
          <div style={card}>
            <h1 style={h1}>{phase === 'error' ? 'Something went wrong' : 'Approval unavailable'}</h1>
            <p style={sub}>{phase === 'error' ? error : unavailableReason(preview?.status)}</p>
            <Box as="button" type="button" onClick={onDismiss} style={button} hover="background:var(--primary-2)">
              Open the dashboard
            </Box>
          </div>
        ) : phase === 'done' && result ? (
          <div style={card} role="status">
            <h1 style={h1}>Award approved</h1>
            <p style={sub}>{result.message}</p>
            <div style={css('font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:4px')}>Purchase orders issued</div>
            <ul style={css('list-style:none;margin:0 0 18px;padding:0')}>
              {result.poNumbers.map((p) => (
                <li key={p.po} style={row}>
                  <span style={css('font-family:var(--mono,monospace);font-weight:600')}>{p.po}</span>
                  <span style={css('color:var(--text-2)')}>{p.supplierName}</span>
                </li>
              ))}
            </ul>
            <Box as="button" type="button" onClick={onDismiss} style={button} hover="background:var(--primary-2)">
              Open the dashboard
            </Box>
          </div>
        ) : preview ? (
          <div style={card}>
            <h1 style={h1}>Approve {preview.packageLabel} award</h1>
            <p style={sub}>
              {preview.projectName}. Quotes leveled to the line: {preview.quotesReceived} of {preview.recipientsTotal} suppliers.
              {preview.suppliers.length > 1
                ? ` Split award recommended${preview.savings > 0 ? `: ${money(preview.savings)} under best single bid` : ''}, freight priced in.`
                : ' Single supplier recommended, freight priced in.'}
            </p>

            <div>
              {preview.suppliers.map((s) => (
                <div key={s.supplierId} style={row}>
                  <span>
                    <span style={css('font-weight:600')}>{s.supplierName}</span>
                    {s.leadDays != null && <span style={css('color:var(--text-3)')}> · {s.leadDays}d lead</span>}
                  </span>
                  <span style={css('font-weight:600')}>{money(s.total)}</span>
                </div>
              ))}
              <div style={css(rowCss + ';font-size:14px;border-top:2px solid var(--border-strong,var(--border))')}>
                <span style={css('font-weight:700')}>Total</span>
                <span style={css('font-weight:700')}>{money(preview.total)}</span>
              </div>
              <div style={css('font-size:12px;color:var(--text-3);margin:2px 0 18px')}>
                {money(preview.material)} material · {money(preview.freight)} freight
                {preview.leadDays != null ? ` · ${preview.leadDays}d lead` : ''}
              </div>
            </div>

            {preview.alreadyAwarded && (
              <div style={css('font-size:12.5px;color:var(--text-2);background:var(--panel-2);border:1px solid var(--border);border-radius:9px;padding:9px 11px;margin-bottom:14px')}>
                This package was already awarded from the dashboard. Approving here is refused; re-award from the comparison screen instead.
              </div>
            )}
            {error && (
              <div role="alert" style={css('font-size:12.5px;color:var(--danger);background:var(--danger-soft,rgba(220,38,38,.1));border:1px solid var(--danger);border-radius:9px;padding:9px 11px;margin-bottom:14px')}>
                {error}
              </div>
            )}

            <Box
              as="button" type="button" onClick={approve} disabled={phase === 'confirming'}
              style={css(buttonCss + `;opacity:${phase === 'confirming' ? '.7' : '1'}`)}
              hover="background:var(--primary-2)"
            >
              {phase === 'confirming' && <span style={css('width:15px;height:15px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;display:inline-block;animation:pcSpin .7s linear infinite')}></span>}
              {phase === 'confirming' ? 'Issuing purchase orders…' : 'Approve award'}
            </Box>
            <p style={css('margin:12px 0 0;font-size:12px;color:var(--text-3);text-align:center')}>
              One click issues the POs and emails every supplier.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  )
}
