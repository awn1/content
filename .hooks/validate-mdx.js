const { readFile } = require('fs-extra');
const mdx = require('@mdx-js/mdx');

const NO_HTML = "<!-- NOT_HTML_DOC -->";
const YES_HTML = "<!-- HTML_DOC -->";

function isHtmlDoc(content) {
    return content.startsWith(YES_HTML) ||
        (!content.startsWith(NO_HTML) && (
            content.startsWith("<p>") ||
            content.startsWith("<!DOCTYPE html>") ||
            (content.includes("<thead>") && content.includes("<tbody>"))
        ));
}

function fixMdx(readmeContent) {
    let txt = readmeContent;

    const replaceTuples = [
        [/<br>(?!<\/br>)/gi, "<br/>"],
        [/<hr>(?!<\/hr>)/gi, "<hr/>"],
        [/<pre>/gi, "<pre>{`"],
        [/<\/pre>/gi, "`}</pre>"]
    ];

    replaceTuples.forEach(([oldPattern, newValue]) => {
        txt = txt.replace(oldPattern, newValue);
    });

    txt = txt.replace(/<!--.*?-->/gs, "");

    return txt;
}

async function parseMDX(file) {
    try {
        let contents = await readFile(file, 'utf8');

        if (isHtmlDoc(contents)) {
            return true;
        }

        contents = fixMdx(contents);
        await mdx(contents);
        return true;
    } catch (error) {
        console.error(`Validation failed in ${file}:`, error.message);
        return false;
    }
}

const files = process.argv.slice(2);

(async () => {
    const results = [];

    // Process files sequentially, one at a time
    for (const file of files) {
        const result = await parseMDX(file);
        results.push(result);
    }

    if (results.includes(false)) {
        process.exit(1);
    }
})();
