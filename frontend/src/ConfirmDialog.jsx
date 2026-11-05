import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

// In-page confirmation popup, used instead of the browser's window.confirm/alert.
//   const confirm = useConfirm();
//   if (await confirm({ title, message, confirmLabel, tone: 'danger' })) { ... }
const ConfirmContext = createContext(null);

export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null);
  const dialogRef = useRef(null), confirmRef = useRef(null), resolveRef = useRef(null);

  const confirm = useCallback(options => new Promise(resolve => {
    resolveRef.current?.(false); // a newer request replaces an unanswered one
    resolveRef.current = resolve;
    setRequest({ confirmLabel: 'Confirm', cancelLabel: 'Cancel', tone: 'primary', ...options });
  }), []);

  function close(answer) {
    resolveRef.current?.(answer);
    resolveRef.current = null;
    setRequest(null);
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (request && !dialog.open) {
      dialog.showModal();
      confirmRef.current?.focus();
    } else if (!request && dialog.open) {
      dialog.close();
    }
  }, [request]);

  return <ConfirmContext.Provider value={confirm}>
    {children}
    <dialog ref={dialogRef} className="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-message"
      onCancel={event => { event.preventDefault(); close(false); }}
      onClick={event => { if (event.target === dialogRef.current) close(false); }}>
      {request && <div className="confirm-body">
        <h2 id="confirm-title">{request.title}</h2>
        {request.message && <p id="confirm-message">{request.message}</p>}
        <div className="confirm-actions">
          <button type="button" className="button subtle" onClick={() => close(false)}>{request.cancelLabel}</button>
          <button type="button" ref={confirmRef} className={`button ${request.tone === 'danger' ? 'danger' : 'dark'}`} onClick={() => close(true)}>{request.confirmLabel}</button>
        </div>
      </div>}
    </dialog>
  </ConfirmContext.Provider>;
}

export function useConfirm() {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error('useConfirm must be used inside <ConfirmProvider>');
  return confirm;
}
