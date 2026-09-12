/**
 * Next.js Web Application Entry Point
 */

import type { NextPage } from 'next';
import Head from 'next/head';
import styles from './page.module.css';

const Home: NextPage = () => {
  return (
    <>
      <Head>
        <title>EA Bot</title>
        <meta name="description" content="EA Bot - Electronic Assistant Bot" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <main className={styles.container}>
        <header className={styles.header}>
          <h1>EA Bot</h1>
          <p>Electronic Assistant Bot Dashboard</p>
        </header>

        <section className={styles.content}>
          <div className={styles.card}>
            <h2>Quick Stats</h2>
            <p>Loading...</p>
          </div>

          <div className={styles.card}>
            <h2>Trade Signals</h2>
            <p>Coming soon</p>
          </div>
        </section>
      </main>
    </>
  );
};

export default Home;
