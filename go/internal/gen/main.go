package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
)

func main() {
	specPath := flag.String("spec", "../openapi/vaquill-us.json", "path to the OpenAPI document")
	outDir := flag.String("out", ".", "directory that receives the generated files")
	flag.Parse()
	spec, err := os.ReadFile(*specPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "gen:", err)
		os.Exit(1)
	}
	files, warnings, err := Generate(spec)
	if err != nil {
		fmt.Fprintln(os.Stderr, "gen:", err)
		os.Exit(1)
	}
	for _, w := range warnings {
		fmt.Fprintln(os.Stderr, "gen warning:", w)
	}
	for name, data := range files {
		if err := os.WriteFile(filepath.Join(*outDir, name), data, 0o644); err != nil {
			fmt.Fprintln(os.Stderr, "gen:", err)
			os.Exit(1)
		}
	}
}
