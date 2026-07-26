import postcss from "postcss";
import fs from "fs";
import path from "path";

export interface ThemeTokens {
  name: string;
  tokens: Record<string, string>;
}

export interface BridgeMapping {
  var: string;
  thVar: string;
}

export function parseThemeFile(filePath: string): ThemeTokens {
  const css = fs.readFileSync(filePath, "utf8");
  const root = postcss.parse(css);

  const tokens: Record<string, string> = {};
  let name = path.basename(filePath, ".css");

  root.walk((node) => {
    if (node.type === "rule") {
      const rule = node;
      const selector = rule.selector;

      const themeMatch = selector?.match(/\.theme-(\w+)/);
      if (themeMatch && themeMatch[1]) name = themeMatch[1];

      rule.walkDecls((decl) => {
        if (decl.prop.startsWith("--th-")) {
          tokens[decl.prop] = decl.value.trim();
        }
      });
    }
  });

  return { name, tokens };
}

export function parseBridge(filePath: string): BridgeMapping[] {
  const css = fs.readFileSync(filePath, "utf8");
  const root = postcss.parse(css);

  const mappings: BridgeMapping[] = [];

  root.walkDecls((decl) => {
    const val = decl.value.trim();
    const varMatch = val.match(/^var\((--th-[^)]+)\)$/);
    if (decl.prop.startsWith("--") && varMatch && varMatch[1]) {
      mappings.push({ var: decl.prop, thVar: varMatch[1] });
    }
  });

  return mappings;
}
