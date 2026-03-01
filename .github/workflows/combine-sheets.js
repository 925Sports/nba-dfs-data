// combine-sheets.js
// Fetches data from two sheets in your Google Spreadsheet and combines them into nba_stats.csv

require('dotenv').config();
const { GoogleSpreadsheet } = require('google-spreadsheet');
const fs = require('fs');

async function combineSheets() {
  try {
    console.log('Starting combine-sheets.js...');

    // 1. Connect to your spreadsheet
    const doc = new GoogleSpreadsheet(process.env.SPREADSHEET_ID);

    await doc.useServiceAccountAuth({
      client_email: process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL,
      private_key: process.env.GOOGLE_PRIVATE_KEY.replace(/\\n/g, '\n'),
    });

    await doc.loadInfo();
    console.log(`Connected to spreadsheet: ${doc.title}`);

    // 2. Get the sheets (make sure names match exactly!)
    const cheatSheet = doc.sheetsByTitle['CHEAT SHEET'];
    const finalProj = doc.sheetsByTitle['FINAL PROJECTIONS'];

    if (!cheatSheet || !finalProj) {
      throw new Error('One or both source sheets not found. Check sheet names.');
    }

    // 3. Load data from both sheets
    const cheatData = await cheatSheet.getRows();
    const finalData = await finalProj.getRows();

    if (cheatData.length === 0 || finalData.length === 0) {
      console.log('One or both sheets are empty. Skipping update.');
      return;
    }

    console.log(`Loaded ${cheatData.length} rows from CHEAT SHEET`);
    console.log(`Loaded ${finalData.length} rows from FINAL PROJECTIONS`);

    // 4. Create lookup map from FINAL PROJECTIONS (key = normalized name | team)
    const finalMap = {};
    const finalHeaders = finalData[0]._sheet.headerValues;

    for (let i = 1; i < finalData.length; i++) {
      const row = finalData[i]._rawData;
      let name = (row[0] || '')
        .toLowerCase()
        .replace(/[^a-z ]/g, '')
        .replace(/`/g, "'")
        .trim();
      const team = (row[2] || '').toUpperCase().trim();
      const key = name + '|' + team;
      finalMap[key] = row;
    }

    // 5. Combine
    const cheatHeaders = cheatData[0]._sheet.headerValues;
    const addedHeaders = finalHeaders.filter(h => !cheatHeaders.includes(h));
    const newHeaders = [...cheatHeaders, ...addedHeaders];

    const newRows = [];
    for (let k = 1; k < cheatData.length; k++) {
      const cRow = cheatData[k]._rawData;
      let cName = (cRow[0] || '')
        .toLowerCase()
        .replace(/[^a-z ]/g, '')
        .replace(/`/g, "'")
        .trim();
      const cTeam = (cRow[2] || '').toUpperCase().trim();
      const key = cName + '|' + cTeam;

      const fRow = finalMap[key] || new Array(finalHeaders.length).fill('');
      const addedValues = addedHeaders.map(h => fRow[finalHeaders.indexOf(h)] || '');

      newRows.push([...cRow, ...addedValues]);
    }

    // 6. Create CSV content
    const csvLines = [
      newHeaders.join(','),
      ...newRows.map(row => row.map(v => `"${(v || '').toString().replace(/"/g, '""')}"`).join(','))
    ];
    const csvContent = csvLines.join('\n');

    // 7. Save to file (GitHub Actions will commit this)
    fs.writeFileSync('nba_stats.csv', csvContent);
    console.log(`Successfully wrote ${newRows.length} players to nba_stats.csv`);

  } catch (error) {
    console.error('Error in combine-sheets.js:', error.message);
    process.exit(1);
  }
}

combineSheets();
