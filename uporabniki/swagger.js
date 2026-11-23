const swaggerJsdoc = require('swagger-jsdoc');

const opcije = {
    definition: {
        openapi: '3.0.0',
        info: {
            title: 'Uporabniki API',
            version: '1.0.0',
            description: 'Mikrostoritev za upravljanje uporabnikov v sistemu FitUra',
        },
        servers: [{ url: 'http://localhost:3001' }],
    },
    apis: ['./index.js'],
};

const specifikacija = swaggerJsdoc(opcije);

module.exports = specifikacija;