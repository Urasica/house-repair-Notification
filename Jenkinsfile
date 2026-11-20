pipeline {
    agent { label 'linux-docker' }

    options {
        skipDefaultCheckout()
        disableConcurrentBuilds()
        timeout(time: 35, unit: 'MINUTES')
        buildDiscarder(logRotator(artifactDaysToKeepStr: '7'))
    }

    environment {
        CI = 'true'
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
                sh 'bash scripts/ci.sh prepare'
            }
        }
        stage('Frontend and contracts') {
            steps { sh 'bash scripts/ci.sh frontend' }
        }
        stage('PostgreSQL and API') {
            steps { sh 'bash scripts/ci.sh backend' }
        }
        stage('Monitoring rules') {
            steps { sh 'bash scripts/ci.sh monitoring' }
        }
        stage('Encrypted backup and restore') {
            steps { sh 'bash scripts/ci.sh restore' }
        }
        stage('Desktop and mobile browser') {
            steps { sh 'bash scripts/ci.sh browser' }
        }
        stage('Concurrent API and recovery') {
            steps { sh 'bash scripts/ci.sh resilience' }
        }
    }

    post {
        always {
            script {
                if (fileExists('scripts/ci.sh')) {
                    sh returnStatus: true, script: 'bash scripts/ci.sh diagnostics'
                    int cleanupStatus = sh(returnStatus: true, script: 'bash scripts/ci.sh cleanup')
                    if (cleanupStatus != 0) {
                        unstable('The isolated test project could not be cleaned up.')
                    }
                }
            }
            junit allowEmptyResults: true, testResults: 'artifacts/junit/*.xml'
            archiveArtifacts allowEmptyArchive: true, artifacts: 'artifacts/ci/*.log,artifacts/m11/*.json,artifacts/playwright/**,artifacts/ui-*/*.png'
        }
    }
}
