import { expect, it } from "vitest"
import { auditSafety } from "./audit-safety"
it("distinguishes blocked attempts from inconsistent enforcement records",()=>{
 const base={required_access:"write",granted_access:"read",decision:"deny",outcome:"not_invoked"} as const
 expect(auditSafety(base)).toBe("blocked")
 expect(auditSafety({...base,decision:"allow",outcome:"success"})).toBe("inconsistent")
 expect(auditSafety({...base,outcome:"error"})).toBe("inconsistent")
 expect(auditSafety({...base,decision:"allow",granted_access:"write",outcome:"success"})).toBe("success")
 expect(auditSafety({...base,decision:"allow",granted_access:"write",outcome:"error"})).toBe("error")
})
