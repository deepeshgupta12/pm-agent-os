// apps/web/src/theme.ts
import { createTheme } from "@mantine/core";

export const theme = createTheme({
  fontFamily:
    "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, Apple Color Emoji, Segoe UI Emoji",

  defaultRadius: "md",

  // Use a calm blue as primary for enterprise console affordances
  primaryColor: "blue",

  components: {
    Card: {
      defaultProps: {
        radius: "md",
        withBorder: false,
      },
    },
    Button: {
      defaultProps: {
        radius: "md",
      },
    },
    TextInput: { defaultProps: { radius: "md" } },
    Textarea: { defaultProps: { radius: "md" } },
    Select: { defaultProps: { radius: "md" } },
    MultiSelect: { defaultProps: { radius: "md" } },
    NumberInput: { defaultProps: { radius: "md" } },
    Badge: {
      defaultProps: {
        radius: "sm",
        variant: "light",
      },
    },
  },
});