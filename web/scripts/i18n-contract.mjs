import ts from "typescript"

const requiredLocales = ["zh-CN", "en-US"]

function unwrapExpression(expression) {
  while (expression && (
    ts.isParenthesizedExpression(expression)
    || ts.isAsExpression(expression)
    || ts.isTypeAssertionExpression(expression)
    || ts.isSatisfiesExpression(expression)
  )) expression = expression.expression
  return expression
}

function readProperties(expression, path) {
  const object = unwrapExpression(expression)
  if (!object || !ts.isObjectLiteralExpression(object)) {
    throw new Error(`${path} must be a static object literal`)
  }
  const properties = new Map()
  for (const property of object.properties) {
    if (!ts.isPropertyAssignment(property) || !(
      ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)
    )) {
      throw new Error(`${path} must use explicit, non-computed properties; dynamic members cannot be checked`)
    }
    const key = property.name.text
    if (properties.has(key)) throw new Error(`${path} contains duplicate key ${JSON.stringify(key)}`)
    properties.set(key, property.initializer)
  }
  return properties
}

/** Read catalog keys without importing or executing the application source. */
export function validateI18nMessages(source, fileName = "i18n.ts") {
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  if (file.parseDiagnostics.length) {
    const diagnostic = file.parseDiagnostics[0]
    const position = file.getLineAndCharacterOfPosition(diagnostic.start ?? 0)
    throw new Error(`${fileName}:${position.line + 1}:${position.character + 1}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`)
  }

  const declarations = file.statements
    .filter(ts.isVariableStatement)
    .flatMap(statement => [...statement.declarationList.declarations])
    .filter(declaration => ts.isIdentifier(declaration.name) && declaration.name.text === "messages")
  if (declarations.length !== 1) {
    throw new Error(`${fileName} must declare exactly one top-level messages object; found ${declarations.length}`)
  }

  const properties = readProperties(declarations[0].initializer, "messages")
  const localeKeys = new Map()
  for (const locale of requiredLocales) {
    if (!properties.has(locale)) throw new Error(`messages is missing locale ${locale}`)
    const keys = new Set(readProperties(properties.get(locale), `messages.${locale}`).keys())
    if (keys.size === 0) throw new Error(`messages.${locale} must contain at least one message key`)
    localeKeys.set(locale, keys)
  }

  const zhKeys = localeKeys.get("zh-CN")
  const enKeys = localeKeys.get("en-US")
  const missingEnglish = [...zhKeys].filter(key => !enKeys.has(key))
  const missingChinese = [...enKeys].filter(key => !zhKeys.has(key))
  const issues = []
  if (missingEnglish.length) issues.push(`en-US is missing keys: ${missingEnglish.join(", ")}`)
  if (missingChinese.length) issues.push(`zh-CN is missing keys: ${missingChinese.join(", ")}`)
  if (issues.length) throw new Error(`messages locales differ; ${issues.join("; ")}`)
  return localeKeys
}
